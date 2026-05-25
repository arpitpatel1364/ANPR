# LPRNet Deep Dive & Research: Indian License Plates

## Background
PaddleOCR is a highly accurate OCR framework, but it is too heavy and consumes too much CPU and RAM for real-time multi-camera processing on an edge CPU (like an i5 13th Gen with 8GB RAM). LPRNet (License Plate Recognition Network) is a much more lightweight, specialized model explicitly designed for license plate recognition.
- **No Character Segmentation:** It uses Connectionist Temporal Classification (CTC) to read the whole sequence at once.
- **Extremely Fast:** It achieves high FPS on CPUs (often 30-50+ FPS) and uses only around ~1.5 - 5 MB of RAM depending on the exact weight configuration.
- **Highly Accurate:** Because it's trained exclusively on plates, it avoids confusion with random background text or irrelevant symbols that general OCR engines struggle with.

## 1. Where to find the Base Model and Weights

The most robust, production-ready implementation of LPRNet in PyTorch is maintained by `sirius-ai`. However, because Indian license plates have different fonts, syntax, and character sets compared to Chinese/European plates, you need a model adapted to the Indian context.

**Recommended Repositories:**
1. **[sirius-ai/LPRNet_Pytorch](https://github.com/sirius-ai/LPRNet_Pytorch)**: This is the gold standard base repository. It is highly optimized, easy to train, and supports ONNX export.
2. **[sanchit2843/Indian_LPR](https://github.com/sanchit2843/Indian_LPR)**: A fork/adaptation specifically focused on Indian plates. This is a great place to look for baseline pre-trained weights for the Indian context, or to see how the character class mappings were adjusted.

> **Tip:** If you cannot find a perfectly accurate pre-trained `.pth` or `.onnx` weight file for Indian plates in the public domain, the standard industry practice is to clone `sirius-ai/LPRNet_Pytorch` and fine-tune it yourself. It is a very small model, meaning it trains very fast even on a mid-range GPU.

## 2. Dataset Preparation for Training

LPRNet does not require bounding boxes for individual characters (unlike YOLO). It reads the whole plate at once. This makes dataset preparation incredibly easy.

### Format Requirements
*   **Image Dimensions:** Every license plate crop must be resized to exactly **94 (width) x 24 (height) pixels**.
*   **Labeling:** Labels are typically provided directly in the filename. For example, an image of a plate `MH12AB1234` should be named `MH12AB1234.jpg`.
*   **Characters:** The neural network needs to know the exact "alphabet" it is looking for. For India, this is usually `['0'-'9', 'A'-'Z']` plus a blank CTC character.

### Creating your Dataset
If you don't have a massive dataset, you can build one quickly:
1. Use your current YOLOv8 + PaddleOCR setup to run on hours of video.
2. Save the `crop_path` images to a folder.
3. Keep only the images where PaddleOCR got the text 100% correct, and rename the images to `THE_PLATE_TEXT.jpg`.
4. Now you have a perfectly formatted, free training dataset!

## 3. How to Train / Fine-Tune LPRNet

Assuming you are using the `sirius-ai` repository, here is the exact workflow:

### Step 1: Update Character Set
In the repository's configuration file, ensure the `CHARS` list perfectly matches the characters found on Indian plates (A-Z, 0-9). Remove Chinese characters to reduce the output layer size and speed up the model.

### Step 2: Organize Folders
Put your training images in a `train/` folder and your validation images in a `valid/` folder.

### Step 3: Run the Training Script
To train from scratch (or fine-tune from a base model), you run the `train_LPRNet.py` script. 

```bash
# Example training command
python train_LPRNet.py \
  --train_img_dirs ./dataset/train/ \
  --test_img_dirs ./dataset/valid/ \
  --max_epoch 100 \
  --train_batch_size 64
```

> **Important:** If you are fine-tuning, you should pass the `--pretrained_model` argument pointing to an existing `.pth` weight file. Fine-tuning an existing model on your custom Indian plate dataset will converge much faster and achieve higher accuracy than training entirely from scratch.

### Step 4: Export to ONNX for your i5 CPU
Once training is complete, use the provided `export_onnx.py` script to convert your `.pth` model to `.onnx`. 
In your `app_multi_camera.py`, you will drop PaddleOCR and replace it with:
```python
import onnxruntime
session = onnxruntime.InferenceSession("lprnet_indian.onnx", providers=['CPUExecutionProvider'])
```

## Ready-To-Paste Research Prompt

Below is a prompt containing the full context of our application. You can paste this into any LLM (like ChatGPT, Claude, etc.) or AI Search Engine (like Perplexity) to gather deep research on replacing PaddleOCR with LPRNet.

```markdown
I am building a Multi-Camera Automatic Number Plate Recognition (ANPR) system in Python. It currently runs on an Intel i5 13th Gen processor with 8GB RAM, completely on CPU.

**Current Architecture:**
1. YOLOv8 (Ultralytics) for vehicle and license plate detection.
2. PaddleOCR for reading the license plate text.
3. Multi-threaded pipeline (1 ThreadPool for API verifications, N threads for Camera reading, 1 global thread for YOLO+OCR processing).

**The Problem:**
PaddleOCR is too heavy and consumes too much CPU and RAM for real-time multi-camera processing on an edge CPU. I want to replace PaddleOCR with a much more lightweight, specialized model: **LPRNet (License Plate Recognition Network)**. 

**My Requirements:**
1. I need to run LPRNet strictly on CPU (using ONNXRuntime or PyTorch).
2. The plates being recognized are **Indian License Plates** (Formats: MH12AB1234, MH12ABC1234, 24BH1234AB).
3. The system needs to be extremely fast and lightweight.

**What I need from you:**
1. A detailed technical breakdown of how to integrate LPRNet into a standard YOLOv8 pipeline in Python.
2. Links, GitHub repositories, or resources where I can find **Pre-trained LPRNet weights for Indian License Plates**, or instructions on how to quickly fine-tune an existing LPRNet model for Indian plates.
3. Code examples of running LPRNet inference using `onnxruntime` or `torch` on CPU, including the image preprocessing steps (resizing, normalization) required before feeding a cropped plate into LPRNet.
4. Any comparison metrics between PaddleOCR and LPRNet for this specific edge-case.
```
