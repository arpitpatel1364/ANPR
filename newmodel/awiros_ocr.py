"""
AwirosOCR — drop-in wrapper for Awiros-ANPR-OCR (PP-OCRv5 / SVTR_HGNet).

Replaces LPRNet's predict_plates_batch() with a higher-accuracy Indian-plate
OCR engine that scores 98.42% on the Awiros held-out validation set vs ~57-65%
for the generic PP-OCRv5 pretrained baseline.

Architecture : PP-OCRv5  (SVTR_HGNet backbone + PPHGNetV2_B4)
Parameters   : 37 M
Training data: 558,767 Indian plate samples (real + synthetic + VLM-cleaned)
Framework    : PaddlePaddle  (completely separate from PyTorch — no conflicts)

Usage (drop-in for predict_plates_batch):
    from newmodel.awiros_ocr import AwirosOCR

    # Load once at startup
    ocr = AwirosOCR(
        weights_path='/path/to/newmodel/model.safetensors',
        dict_path='/path/to/newmodel/en_dict.txt',
        use_gpu=True,   # auto-falls-back to CPU if CUDA unavailable
    )

    # During inference loop (same signature as predict_plates_batch)
    texts = ocr.predict_batch(list_of_bgr_crops)   # -> list[str]
    text  = ocr.predict(single_bgr_crop)            # -> str
"""

from __future__ import annotations

import copy
import logging
import subprocess
import sys
from pathlib import Path
from typing import List

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# PP-OCRv5 Model configuration — mirrors Awiros test.py exactly
# ---------------------------------------------------------------------------
_CTC_NUM_CLASSES  = 64
_NRTR_NUM_CLASSES = 67  # NRTRHead internally +1 → 68 to match weights

_MODEL_CONFIG = {
    "Architecture": {
        "model_type": "rec",
        "algorithm": "SVTR_HGNet",
        "Transform": None,
        "Backbone": {"name": "PPHGNetV2_B4", "text_rec": True},
        "Head": {
            "name": "MultiHead",
            "out_channels_list": {
                "CTCLabelDecode": _CTC_NUM_CLASSES,
                "NRTRLabelDecode": _NRTR_NUM_CLASSES,
            },
            "head_list": [
                {
                    "CTCHead": {
                        "Neck": {
                            "name": "svtr",
                            "dims": 120,
                            "depth": 2,
                            "hidden_dims": 120,
                            "kernel_size": [1, 3],
                            "use_guide": True,
                        },
                        "Head": {"fc_decay": 1e-05},
                    }
                },
                {"NRTRHead": {"nrtr_dim": 384, "max_text_length": 25}},
            ],
        },
    },
}

# Target input shape: [C, H, W]
_IMAGE_SHAPE = [3, 48, 320]

# ---------------------------------------------------------------------------
# PaddleOCR repo bootstrap — only the model architecture (ppocr.modeling)
# is imported, which has no pyclipper/shapely dependency.
# ---------------------------------------------------------------------------
_NEWMODEL_DIR = Path(__file__).resolve().parent


def _find_ppocr_root() -> "Path | None":
    """Search well-known locations for a PaddleOCR checkout."""
    candidates = [
        _NEWMODEL_DIR / "PaddleOCR",
        _NEWMODEL_DIR.parent / "PaddleOCR",
        Path.cwd() / "PaddleOCR",
        Path.cwd(),
        _NEWMODEL_DIR,
    ]
    for c in candidates:
        if (c / "ppocr" / "__init__.py").is_file():
            return c
    return None


def _ensure_ppocr_importable() -> None:
    """Make ppocr importable. Auto-clones PaddleOCR if not found."""
    root = _find_ppocr_root()
    if root is None:
        clone_target = _NEWMODEL_DIR / "PaddleOCR"
        logging.info(f"[AwirosOCR] ppocr not found — cloning into {clone_target} ...")
        subprocess.check_call([
            "git", "clone", "--depth", "1",
            "https://github.com/PaddlePaddle/PaddleOCR.git",
            str(clone_target),
        ])
        root = clone_target

    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    logging.info(f"[AwirosOCR] ppocr root: {root_str}")


# ---------------------------------------------------------------------------
# Minimal self-contained CTC decoder
# Extracted directly from ppocr/postprocess/rec_postprocess.py so we do NOT
# import that module (its __init__.py cascade-imports pyclipper / shapely
# which are unrelated DB-detector post-processors).
# ---------------------------------------------------------------------------
class _CTCDecoder:
    """Minimal CTC greedy decoder — zero extra dependencies."""

    def __init__(self, dict_path: str, use_space_char: bool = True) -> None:
        chars: List[str] = []
        with open(dict_path, "rb") as f:
            for line in f:
                ch = line.decode("utf-8").strip("\n").strip("\r\n")
                chars.append(ch)
        if use_space_char:
            chars.append(" ")
        # CTC: index 0 is the blank token; shift everything by 1
        self.characters = ["blank"] + chars

    def __call__(self, preds_np: np.ndarray) -> List[str]:
        """
        Decode a batch of CTC logits.

        Args:
            preds_np : numpy array shape (N, T, num_classes)

        Returns:
            List of decoded text strings, one per sample.
        """
        texts = []
        N = preds_np.shape[0]
        for i in range(N):
            seq = preds_np[i]                   # (T, num_classes)
            indices = seq.argmax(axis=-1)        # greedy argmax over classes
            # CTC collapse: remove blanks (index 0) and consecutive repeats
            collapsed = []
            prev = None
            for idx in indices:
                if idx != 0 and idx != prev:    # not blank, not repeat
                    collapsed.append(int(idx))
                prev = idx
            text = "".join(
                self.characters[c] for c in collapsed
                if c < len(self.characters)
            )
            texts.append(text.strip().upper())
        return texts


# ---------------------------------------------------------------------------
# Preprocessing helpers — mirrors test.py exactly
# ---------------------------------------------------------------------------
def _resize_for_rec(img_bgr: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    """Resize maintaining aspect ratio; zero-pad on the right."""
    img_h, img_w = img_bgr.shape[:2]
    ratio = target_h / max(img_h, 1)
    new_w = min(int(img_w * ratio), target_w)
    resized = cv2.resize(img_bgr, (new_w, target_h), interpolation=cv2.INTER_LINEAR)
    if new_w < target_w:
        padded = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        padded[:, :new_w] = resized
        return padded
    return resized


def _preprocess(img_bgr: np.ndarray) -> np.ndarray:
    """BGR uint8 crop → float32 CHW tensor normalised to [-1, 1]."""
    _, target_h, target_w = _IMAGE_SHAPE
    img = _resize_for_rec(img_bgr, target_h, target_w)
    img = img.astype(np.float32) / 255.0
    img = (img - 0.5) / 0.5
    return img.transpose((2, 0, 1))   # HWC → CHW


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------
class AwirosOCR:
    """
    Awiros-ANPR-OCR inference wrapper.

    Thread-safety note:
        PaddlePaddle inference is not thread-safe by default.
        inference_supervisor_loop() is a single thread so no locking needed.
        If multi-threaded access is ever required, protect predict_batch()
        with a threading.Lock.
    """

    def __init__(
        self,
        weights_path: str,
        dict_path: str,
        use_gpu: bool = False,
    ) -> None:
        """
        Args:
            weights_path : Absolute path to model.safetensors
            dict_path    : Absolute path to en_dict.txt
            use_gpu      : Use CUDA if available; silently falls back to CPU.
                           Overridden by the ANPR_PADDLE_DEVICE env var when set
                           (written by `./run.sh setup-paddle`).
        """
        import os as _os
        # Honour the device saved by `./run.sh setup-paddle`.
        # ANPR_PADDLE_DEVICE=gpu  → GPU mode
        # ANPR_PADDLE_DEVICE=cpu  → CPU mode  (default if file not set)
        env_device = _os.environ.get("ANPR_PADDLE_DEVICE", "").strip().lower()
        if env_device == "gpu":
            use_gpu = True
        elif env_device == "cpu":
            use_gpu = False
        # else: honour the use_gpu argument as-is

        _ensure_ppocr_importable()

        # Late imports — paddle and ppocr.modeling are loaded here so that
        # the module can be imported even when paddle is not yet installed;
        # the ImportError surfaces only at instantiation time.
        try:
            import paddle
            # Import ONLY the model-builder — avoids ppocr's __init__ cascade
            # that would pull in pyclipper/shapely (DB text-detector deps).
            from ppocr.modeling.architectures import build_model as _build_model
            from safetensors.numpy import load_file as _sf_load
        except ImportError as exc:
            raise ImportError(
                "[AwirosOCR] Missing dependency.\n"
                "Run:  pip install paddlepaddle safetensors\n"
                f"Original error: {exc}"
            ) from exc

        # ── Device ───────────────────────────────────────────────────────────
        if use_gpu and paddle.is_compiled_with_cuda():
            paddle.set_device("gpu")
            self._device_label = "GPU"
        else:
            paddle.set_device("cpu")
            self._device_label = "CPU"
            if use_gpu:
                logging.warning(
                    "[AwirosOCR] GPU requested but PaddlePaddle CUDA unavailable — "
                    "falling back to CPU."
                )

        # ── Self-contained CTC decoder (no ppocr postprocess import) ─────────
        self._decoder = _CTCDecoder(dict_path=dict_path, use_space_char=True)

        # ── Build PP-OCRv5 model ─────────────────────────────────────────────
        config = copy.deepcopy(_MODEL_CONFIG)
        self._model = _build_model(config["Architecture"])
        self._model.eval()

        # ── Load safetensors weights ──────────────────────────────────────────
        np_state = _sf_load(weights_path)
        state_dict = {k: paddle.to_tensor(v) for k, v in np_state.items()}
        self._model.set_state_dict(state_dict)

        self._paddle = paddle

        logging.info(
            f"[AwirosOCR] Loaded from {weights_path} (device={self._device_label})"
        )
        print(
            f"✅ [AwirosOCR] PP-OCRv5 model loaded on {self._device_label} "
            f"— 98.42% accuracy on Indian plates"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def predict(self, crop_bgr: np.ndarray) -> str:
        """
        OCR a single BGR plate crop.

        Returns:
            Plate text (uppercase string), e.g. "MH12AB1234".
            Returns "" for unreadable / abstained plates.
        """
        results = self.predict_batch([crop_bgr])
        return results[0] if results else ""

    def predict_batch(self, crops: List[np.ndarray]) -> List[str]:
        """
        OCR a batch of BGR plate crops.

        Drop-in replacement for LPRNet's predict_plates_batch().

        Args:
            crops : list of numpy uint8 BGR images (any size — resized internally)

        Returns:
            list[str] of uppercase plate texts, same order as input.
            Items are "" for unreadable / abstained crops.
        """
        if not crops:
            return []

        import paddle

        # ── Batch preprocess ──────────────────────────────────────────────────
        batch_np = np.stack(
            [_preprocess(c) for c in crops], axis=0
        ).astype(np.float32)                         # (N, 3, 48, 320)

        batch_tensor = paddle.to_tensor(batch_np)

        # ── Forward pass ──────────────────────────────────────────────────────
        with paddle.no_grad():
            preds = self._model(batch_tensor)

        # MultiHead returns dict; use CTC logits
        if isinstance(preds, dict):
            pred_tensor = preds.get("ctc", next(iter(preds.values())))
        elif isinstance(preds, (list, tuple)):
            pred_tensor = preds[0]
        else:
            pred_tensor = preds

        # pred_tensor shape: (N, T, C) or (N, C, T)
        preds_np = pred_tensor.numpy()

        # Dynamic transpose to (N, T, num_classes) for the CTC decoder.
        # PP-OCRv5 outputs (N, T, C) directly, so no transpose is needed.
        # Older models might output (N, C, T), which requires transposing.
        if preds_np.ndim == 3:
            if preds_np.shape[1] == _CTC_NUM_CLASSES and preds_np.shape[2] != _CTC_NUM_CLASSES:
                preds_np = preds_np.transpose(0, 2, 1)

        # ── Decode ────────────────────────────────────────────────────────────
        texts = self._decoder(preds_np)

        # Safety guard — shouldn't happen but keeps the contract clean
        while len(texts) < len(crops):
            texts.append("")

        return texts
