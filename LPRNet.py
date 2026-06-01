import torch
import torch.nn as nn
import cv2
import numpy as np

CHARS = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
         'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J',
         'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T',
         'U', 'V', 'W', 'X', 'Y', 'Z', '-']

class small_basic_block(nn.Module):
    def __init__(self, ch_in, ch_out):
        super(small_basic_block, self).__init__()
        self.block = nn.Sequential(
            nn.Conv2d(ch_in, ch_out // 4, kernel_size=1),
            nn.ReLU(),
            nn.Conv2d(ch_out // 4, ch_out // 4, kernel_size=(3, 1), padding=(1, 0)),
            nn.ReLU(),
            nn.Conv2d(ch_out // 4, ch_out // 4, kernel_size=(1, 3), padding=(0, 1)),
            nn.ReLU(),
            nn.Conv2d(ch_out // 4, ch_out, kernel_size=1),
        )
    def forward(self, x):
        return self.block(x)

class LPRNet(nn.Module):
    def __init__(self, class_num, dropout_rate):
        super(LPRNet, self).__init__()
        self.class_num = class_num
        self.backbone = nn.Sequential(
            nn.Conv2d(in_channels=3, out_channels=64, kernel_size=3, stride=1),
            nn.BatchNorm2d(num_features=64),
            nn.ReLU(),
            nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(1, 1, 1)),
            small_basic_block(ch_in=64, ch_out=128),
            nn.BatchNorm2d(num_features=128),
            nn.ReLU(),
            nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(2, 1, 2)),
            small_basic_block(ch_in=64, ch_out=256),
            nn.BatchNorm2d(num_features=256),
            nn.ReLU(),
            small_basic_block(ch_in=256, ch_out=256),
            nn.BatchNorm2d(num_features=256),
            nn.ReLU(),
            nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(4, 1, 2)),
            nn.Dropout(dropout_rate),
            nn.Conv2d(in_channels=64, out_channels=256, kernel_size=(1, 4), stride=1),
            nn.BatchNorm2d(num_features=256),
            nn.ReLU(),
            nn.Dropout(dropout_rate),
            nn.Conv2d(in_channels=256, out_channels=class_num, kernel_size=(13, 1), stride=1),
            nn.BatchNorm2d(num_features=class_num),
            nn.ReLU(),
        )
        self.container = nn.Sequential(
            nn.Conv2d(in_channels=64+128+256+self.class_num, out_channels=self.class_num, kernel_size=(1, 1), stride=(1, 1)),
        )
        self.avgpool1 = nn.AvgPool2d(kernel_size=5, stride=5)
        self.avgpool2 = nn.AvgPool2d(kernel_size=(4, 10), stride=(4, 2))

    def forward(self, x):
        keep_features = list()
        for i, layer in enumerate(self.backbone.children()):
            x = layer(x)
            if i in [2, 6, 13, 22]:
                keep_features.append(x)

        global_context = list()
        for i, f in enumerate(keep_features):
            if i in [0, 1]:
                f = self.avgpool1(f)
            if i in [2]:
                f = self.avgpool2(f)
            f_pow = torch.pow(f, 2)
            f_mean = torch.mean(f_pow)
            f = torch.div(f, f_mean)
            global_context.append(f)

        x = torch.cat(global_context, 1)
        x = self.container(x)
        logits = torch.mean(x, dim=2)
        return logits

def ctc_beam_search(probs, beam_width=3, chars=None, return_beams=False):
    """
    CTC beam search decoder for LPRNet output.
    Replaces greedy argmax with top-K beam tracking.

    Args:
        probs     : numpy array shape (T, num_classes)
                    — softmax output from LPRNet, T timesteps
        beam_width: int, number of beams to track (default 3)
        chars     : list of characters matching model's class order
                    (same char list used by existing greedy decode)
        return_beams: bool, whether to return the full list of beams

    Returns:
        best_string : str — top beam result after CTC collapse
    """
    import numpy as np

    T, C = probs.shape
    blank = C - 1  # CTC blank token — last index by convention

    # Each beam: (prefix_string, last_char, cumulative_log_prob)
    beams = [("", blank, 0.0)]

    for t in range(T):
        new_beams = {}

        for prefix, last_char, log_prob in beams:
            # Top-K classes at this timestep (pruning)
            top_k = np.argsort(probs[t])[::-1][:max(beam_width * 2, 10)]

            for c in top_k:
                p = probs[t][c]
                if p < 1e-10:
                    continue
                new_log_prob = log_prob + np.log(p)

                if c == blank:
                    # Blank: carry prefix forward, reset last_char
                    key = (prefix, blank)
                    if key not in new_beams or new_beams[key][1] < new_log_prob:
                        new_beams[key] = (prefix, blank, new_log_prob)
                elif c == last_char:
                    # Repeat without blank: CTC collapse — do not extend
                    key = (prefix, c)
                    if key not in new_beams or new_beams[key][1] < new_log_prob:
                        new_beams[key] = (prefix, c, new_log_prob)
                else:
                    # New character: extend prefix
                    char = chars[c] if chars else str(c)
                    new_prefix = prefix + char
                    key = (new_prefix, c)
                    if key not in new_beams or new_beams[key][1] < new_log_prob:
                        new_beams[key] = (new_prefix, c, new_log_prob)

        # Keep top beam_width beams by log probability
        beams = sorted(new_beams.values(), key=lambda x: -x[2])[:beam_width]

    if return_beams:
        return beams
    # Return best prefix (highest log prob)
    return beams[0][0] if beams else ""


import re as _re

# Comprehensive Indian plate regex — covers old, new, and BH formats
# Old format : GJ01AB1234
# New format : MH12ABC1234
# BH format  : 24BH1234AB
INDIAN_PLATE_REGEX = _re.compile(
    r'^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{1,4}$'   # old + new
    r'|^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$'            # BH series
)

def apply_format_filter(beam_results, regex=INDIAN_PLATE_REGEX):
    """
    Pick the first beam result that matches the plate format regex.
    Falls back to top beam (index 0) if none match.

    Args:
        beam_results : list of (prefix, last_char, log_prob) tuples
                       — the full beams list from ctc_beam_search
                       OR a list of plain strings
        regex        : compiled re.Pattern for valid plate formats

    Returns:
        plate_str : str — best matching plate string
    """
    for beam in beam_results:
        # Handle both tuple format and plain string list
        s = beam[0] if isinstance(beam, tuple) else beam
        if regex.match(s):
            return s
    # No beam matched format — return raw top result
    top = beam_results[0] if beam_results else ""
    return top[0] if isinstance(top, tuple) else top


def decode(preds, chars):
    # greedy decode
    pred_labels = list()
    labels = list()
    for i in range(preds.shape[0]):
        pred = preds[i, :, :]
        pred_label = list()
        for j in range(pred.shape[1]):
            pred_label.append(np.argmax(pred[:, j], axis=0))
        no_repeat_blank_label = list()
        pre_c = pred_label[0]
        if pre_c != len(chars) - 1:
            no_repeat_blank_label.append(pre_c)
        for c in pred_label:
            if (pre_c == c) or (c == len(chars) - 1):
                if c == len(chars) - 1:
                    pre_c = c
                continue
            no_repeat_blank_label.append(c)
            pre_c = c
        pred_labels.append(no_repeat_blank_label)
        
    for i, label in enumerate(pred_labels):
        lb = ""
        for i in label:
            lb += chars[i]
        labels.append(lb)
    return labels

def predict_plate(model, image, device='cpu'):
    # Resize and normalize image for LPRNet
    img = cv2.resize(image, (94, 24))
    img = img.astype('float32')
    img -= 127.5
    img *= 0.0078125
    img = np.transpose(img, (2, 0, 1))
    
    img_tensor = torch.from_numpy(img).unsqueeze(0).to(device)
    
    with torch.inference_mode():
        preds = model(img_tensor)
    
    beam_search_enabled = True
    beam_width = 3
    
    if beam_search_enabled:
        probs_tensor = torch.softmax(preds, dim=1)
        probs = probs_tensor.cpu().numpy()
        probs = np.transpose(probs[0], (1, 0)) # transpose (class_num, T) to (T, class_num)
        beams = ctc_beam_search(probs, beam_width=beam_width, chars=CHARS, return_beams=True)
        license_plate_text = apply_format_filter(beams)
    else:
        preds = preds.cpu().numpy()
        labels = decode(preds, CHARS)
        license_plate_text = labels[0]
        
    return license_plate_text

def predict_plates_batch(model, images, device='cpu'):
    if not images:
        return []
        
    img_tensors = []
    for image in images:
        img = cv2.resize(image, (94, 24))
        img = img.astype('float32')
        img -= 127.5
        img *= 0.0078125
        img = np.transpose(img, (2, 0, 1))
        img_tensors.append(torch.from_numpy(img))
        
    batch_tensor = torch.stack(img_tensors).to(device)
    
    with torch.inference_mode():
        preds = model(batch_tensor)
        
    beam_search_enabled = True
    beam_width = 3
    results = []
    
    if beam_search_enabled:
        probs_tensor = torch.softmax(preds, dim=1)
        probs_batch = probs_tensor.cpu().numpy()
        for b in range(probs_batch.shape[0]):
            probs = np.transpose(probs_batch[b], (1, 0))
            beams = ctc_beam_search(probs, beam_width=beam_width, chars=CHARS, return_beams=True)
            license_plate_text = apply_format_filter(beams)
            results.append(license_plate_text)
    else:
        preds = preds.cpu().numpy()
        labels = decode(preds, CHARS)
        results = labels
        
    return results
