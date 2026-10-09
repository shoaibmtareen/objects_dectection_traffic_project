"""Second-stage crop classifier (CLIP zero-shot).

YOLO (trained on COCO) has no class for auto-rickshaws, so it calls them car,
truck or bus. Each tracked vehicle's best crop is checked a few times with CLIP
against text prompts; the result overrides YOLO's label when CLIP is confident.
"""
from pathlib import Path

import cv2
import numpy as np
import torch

# (prompt, class) — several prompts per class, probabilities are summed per class
PROMPTS = [
    ("a photo of a car", "Car"), ("a photo of a taxi", "Car"), ("a photo of an SUV", "Car"),
    ("a photo of a van", "Car"),
    ("a photo of a truck", "Truck"), ("a photo of a pickup truck", "Truck"), ("a photo of a lorry", "Truck"),
    ("a photo of a small cargo truck", "Truck"), ("a photo of a mini truck", "Truck"),
    ("a photo of a delivery truck", "Truck"),
    ("a photo of a bus", "Bus"),
    ("a photo of an auto rickshaw", "Rickshaw"), ("a photo of a tuk tuk", "Rickshaw"),
    ("a photo of a three-wheeler auto rickshaw", "Rickshaw"), ("a photo of the back of an auto rickshaw", "Rickshaw"),
    ("a photo of a black and yellow auto rickshaw", "Rickshaw"),
    ("a photo of a green and yellow auto rickshaw", "Rickshaw"),
    ("a photo of a motorcycle", "Motorcycle"), ("a photo of a scooter", "Motorcycle"),
    ("a photo of a bicycle", "Bicycle"),
    ("a photo of a pedestrian walking", "Person"),  # only offered when YOLO said bicycle
    # not a vehicle at all: YOLO false positives (signs, poles, boards) get hidden
    ("a photo of a road sign", "Other"), ("a photo of a signboard", "Other"),
    ("a photo of a traffic sign on a pole", "Other"), ("a photo of a street light pole", "Other"),
]

# prompts for a "person" detection: rider (bike not detected) or pedestrian
PERSON_PROMPTS = [
    ("a photo of a person riding a motorcycle", "Motorcycle"), ("a photo of a person riding a scooter", "Motorcycle"),
    ("a photo of a person riding a bicycle", "Bicycle"),
    ("a photo of a pedestrian walking", "Person"), ("a photo of a person standing on the roadside", "Person"),
]

# which labels CLIP may choose between, given YOLO's label
CANDIDATES = {
    "Car": {"Car", "Truck", "Bus", "Rickshaw", "Other"},
    "Truck": {"Car", "Truck", "Bus", "Rickshaw", "Other"},
    "Bus": {"Car", "Truck", "Bus", "Rickshaw", "Other"},
    "Motorcycle": {"Motorcycle", "Rickshaw"},
    "Bicycle": {"Bicycle", "Person"},
}


class CropClassifier:
    def __init__(self, model_dir: str, model_name: str = "ViT-B/32", device: str = "cpu"):
        import clip  # imported lazily: only needed when the classifier is enabled

        Path(model_dir).mkdir(parents=True, exist_ok=True)
        self.device = "cuda" if device not in ("cpu", "") and torch.cuda.is_available() else "cpu"
        self.model, self.preprocess = clip.load(model_name, device=self.device, download_root=model_dir)
        self.model.eval()
        with torch.no_grad():
            text = self.model.encode_text(clip.tokenize([p for p, _ in PROMPTS]).to(self.device))
            self.text_features = text / text.norm(dim=-1, keepdim=True)
            ptext = self.model.encode_text(clip.tokenize([p for p, _ in PERSON_PROMPTS]).to(self.device))
            self.person_features = ptext / ptext.norm(dim=-1, keepdim=True)
        self.prompt_classes = [c for _, c in PROMPTS]
        self.person_classes = [c for _, c in PERSON_PROMPTS]
        self.disabled_labels: set[str] = set()

    @staticmethod
    def needs_check(yolo_label: str) -> bool:
        return yolo_label in CANDIDATES or yolo_label == "Person"

    def _probs(self, crop_bgr: np.ndarray, text_features, classes: list[str], idx: list[int]) -> dict[str, float]:
        from PIL import Image

        image = Image.fromarray(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB))
        with torch.no_grad():
            feats = self.model.encode_image(self.preprocess(image).unsqueeze(0).to(self.device))
            feats = feats / feats.norm(dim=-1, keepdim=True)
            probs = (100.0 * feats @ text_features[idx].T).softmax(dim=-1)[0].cpu().tolist()
        out: dict[str, float] = {}
        for i, p in zip(idx, probs):
            out[classes[i]] = out.get(classes[i], 0.0) + p
        return out

    def classify_person(self, crop_bgr: np.ndarray) -> dict[str, float]:
        """Is this 'person' riding a motorcycle / bicycle, or on foot?"""
        if crop_bgr is None or crop_bgr.size == 0:
            return {}
        idx = [i for i, c in enumerate(self.person_classes) if c not in self.disabled_labels]
        return self._probs(crop_bgr, self.person_features, self.person_classes, idx)

    def classify(self, crop_bgr: np.ndarray, yolo_label: str) -> dict[str, float]:
        """Class probabilities (summed over prompts) restricted to sensible alternatives."""
        allowed = CANDIDATES.get(yolo_label, set()) - self.disabled_labels
        allowed.add(yolo_label)
        idx = [i for i, c in enumerate(self.prompt_classes) if c in allowed]
        if not idx or crop_bgr is None or crop_bgr.size == 0:
            return {}
        return self._probs(crop_bgr, self.text_features, self.prompt_classes, idx)
