# ================================================================
# plant_disease_api.py
# Production Ensemble API — ViT-B/16 + Swin-Tiny
# 
# Pipeline:
#   upload → image_quality_check → ood_gate → grabcut_crop
#           → ensemble_predict → tier + advice → response
# ================================================================

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import torch
import torch.nn as nn
import torchvision.models as models
import torchvision.transforms as transforms
import torch.nn.functional as F
from PIL import Image, UnidentifiedImageError
import cv2
import numpy as np
import io
import json
import math
import time
import logging

# ================================================================
# LOGGING
# Structured logs — every request gets a latency breakdown so
# you can see exactly where time is being spent in production.
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("plant_api")

app = FastAPI(
    title="Plant Disease Ensemble API",
    description="ViT-B/16 + Swin-Tiny dynamic fusion — 38 PlantVillage classes",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
)

device      = torch.device("cpu")
NUM_CLASSES = 38

# ----------------------------------------------------------------
# BASE WEIGHTS
# ----------------------------------------------------------------
BASE_WEIGHT_VIT  = 0.70
BASE_WEIGHT_SWIN = 0.30

# ----------------------------------------------------------------
# DYNAMIC SHIFT WEIGHTS
# ----------------------------------------------------------------
VIT_DOM_WEIGHT_VIT   = 0.85
VIT_DOM_WEIGHT_SWIN  = 0.15
SWIN_DOM_WEIGHT_VIT  = 0.20
SWIN_DOM_WEIGHT_SWIN = 0.80
SWIN_DOMINANCE_RATIO = 3.0

# ----------------------------------------------------------------
# CONFIDENCE TIERS
# ----------------------------------------------------------------
CONFIDENCE_HIGH   = 0.75
CONFIDENCE_MEDIUM = 0.50

# ----------------------------------------------------------------
# OOD (Out-Of-Distribution) DETECTION
#
# Shannon entropy of the 38-class probability distribution.
# Max possible entropy for 38 classes = log2(38) ≈ 5.25 bits.
#
# Calibration guide — run these through /predict/debug and read
# the ood_entropy field to tune OOD_ENTROPY_THRESHOLD:
#   Real diseased leaf (close-up):   entropy ≈ 0.8 – 2.5
#   Real healthy leaf (close-up):    entropy ≈ 1.0 – 2.8
#   Whole plant photo:               entropy ≈ 3.0 – 4.2
#   Landscape / non-plant image:     entropy ≈ 4.0 – 5.1
#   Pure noise / solid colour:       entropy ≈ 5.0 – 5.25
#
# 4.0 is a safe starting threshold. Lower it (e.g. 3.5) to be
# more aggressive about rejection. Raise it (e.g. 4.5) if you
# are getting false rejections on unusual but valid leaf photos.
# ----------------------------------------------------------------
OOD_ENTROPY_THRESHOLD = 4.0

# ----------------------------------------------------------------
# IMAGE QUALITY GATES
# ----------------------------------------------------------------
MIN_IMAGE_SIZE_PX   = 100        # reject images smaller than 100×100
MAX_IMAGE_SIZE_MB   = 15         # reject uploads over 15 MB
MIN_CROP_SIZE_PX    = 64         # reject GrabCut crops smaller than 64×64
BLUR_THRESHOLD      = 80.0       # Laplacian variance — below this = too blurry
                                 # Tune: sharp leaf ≈ 200+, blurry ≈ 20–60

# ----------------------------------------------------------------
# HARD CLASSES
# ----------------------------------------------------------------
HARD_CLASSES = {
    "Tomato___Tomato_Yellow_Leaf_Curl_Virus",
    "Orange___Haunglongbing_(Citrus_greening)",
    "Soybean___healthy",
    "Tomato___Bacterial_spot",
    "Tomato___Late_blight",
}


# ================================================================
# MODEL LOADING
# ================================================================
log.info("Loading models...")

vit_model = models.vit_b_16(weights=None)
vit_model.heads.head = nn.Linear(
    vit_model.heads.head.in_features, NUM_CLASSES
)
vit_model.load_state_dict(
    torch.load("models/best_model.pth", map_location=device)
)
vit_model = vit_model.to(device)
vit_model.eval()

swin_model = models.swin_t(weights=None)
swin_model.head = nn.Linear(
    swin_model.head.in_features, NUM_CLASSES
)
swin_model.load_state_dict(
    torch.load("models/swin-model.pth", map_location=device)
)
swin_model = swin_model.to(device)
swin_model.eval()

log.info("Models loaded. ViT + Swin ready.")

with open("classes.json") as f:
    class_names = json.load(f)

# ================================================================
# TRANSFORM
# ================================================================
transform = transforms.Compose([
    transforms.Resize((256, 256)),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225]
    )
])


# ================================================================
# STAGE 1 — IMAGE QUALITY CHECKS
#
# Run these before any ML computation so bad inputs are rejected
# cheaply. Order matters: file size first (cheapest), then decode,
# then blur (requires OpenCV), then OOD (requires a forward pass).
# ================================================================

def check_file_size(image_bytes: bytes) -> None:
    """Reject oversized uploads before attempting to decode."""
    size_mb = len(image_bytes) / (1024 * 1024)
    if size_mb > MAX_IMAGE_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"Image too large ({size_mb:.1f} MB). Maximum is {MAX_IMAGE_SIZE_MB} MB."
        )


def check_image_dimensions(pil_image: Image.Image) -> None:
    """Reject images that are too small to contain useful leaf detail."""
    w, h = pil_image.size
    if w < MIN_IMAGE_SIZE_PX or h < MIN_IMAGE_SIZE_PX:
        raise HTTPException(
            status_code=422,
            detail=f"Image too small ({w}×{h}px). Minimum is {MIN_IMAGE_SIZE_PX}×{MIN_IMAGE_SIZE_PX}px."
        )


def check_blur(pil_image: Image.Image) -> float:
    """
    Laplacian variance blur detection.

    How it works: the Laplacian operator measures the second
    derivative of pixel intensity — edges produce high values,
    flat regions produce near-zero values. A sharp image has many
    strong edges → high variance. A blurry image has soft edges
    → low variance.

    Returns the variance score. Raises HTTPException if too blurry.
    """
    gray = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2GRAY)
    variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    log.info(f"Blur score (Laplacian variance): {variance:.1f}")

    if variance < BLUR_THRESHOLD:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Image is too blurry (score: {variance:.1f}, minimum: {BLUR_THRESHOLD}). "
                "Please retake with better focus and lighting."
            )
        )
    return variance


# ================================================================
# STAGE 2 — GRABCUT LEAF EXTRACTION
#
# Separates foreground (plant) from background using OpenCV's
# GrabCut algorithm (iterative graph-cut segmentation).
#
# Why GrabCut over YOLO here:
#   - Zero extra model weights
#   - OpenCV is already a transitive dependency of torchvision
#   - Works well when subject is roughly centred (phone photos)
#   - Fast: ~30–80ms on CPU for a 500px image
#
# Failure modes:
#   - Complex textured backgrounds (bark, patterned fabric)
#   - Very dark or very overexposed images
#   - Subject at extreme edge of frame
# In all failure cases it returns the original image — safe fallback.
# ================================================================

def grabcut_extract(pil_image: Image.Image) -> tuple[Image.Image, bool]:
    """
    Extracts foreground region using GrabCut.
    Returns (cropped_image, was_cropped).

    was_cropped=True  → a meaningful foreground region was found
                        and the image was cropped to it.
    was_cropped=False → GrabCut failed or found nothing useful;
                        original image is returned unchanged.
    """
    img_rgb = np.array(pil_image)
    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    h, w    = img_bgr.shape[:2]

    # Resize to max 600px on the long side for GrabCut speed.
    # We crop back from the original resolution after, so detail
    # is not lost — only the mask is computed at reduced resolution.
    scale = 1.0
    if max(h, w) > 600:
        scale = 600.0 / max(h, w)
        small = cv2.resize(img_bgr, (int(w * scale), int(h * scale)))
    else:
        small = img_bgr.copy()

    sh, sw = small.shape[:2]

    mask    = np.zeros((sh, sw), np.uint8)
    bgd_mdl = np.zeros((1, 65), np.float64)
    fgd_mdl = np.zeros((1, 65), np.float64)

    # Initial rect: 5% inset from all edges.
    # Assumes subject is roughly centred — valid for most phone photos.
    margin_x = int(sw * 0.05)
    margin_y = int(sh * 0.05)
    rect = (margin_x, margin_y, sw - 2 * margin_x, sh - 2 * margin_y)

    try:
        cv2.grabCut(small, mask, rect, bgd_mdl, fgd_mdl, 5, cv2.GC_INIT_WITH_RECT)
    except cv2.error as e:
        log.warning(f"GrabCut failed: {e}. Using original image.")
        return pil_image, False

    # GrabCut labels: 0=bg, 1=fg, 2=probable_bg, 3=probable_fg
    # Treat both definite and probable foreground as foreground.
    fg_mask = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1, 0).astype(np.uint8)

    # Find bounding box of foreground in the scaled mask
    coords = cv2.findNonZero(fg_mask)
    if coords is None:
        log.info("GrabCut found no foreground. Using original image.")
        return pil_image, False

    x, y, bw, bh = cv2.boundingRect(coords)
    fg_area  = int(fg_mask.sum())
    img_area = sh * sw

    # Reject if foreground is less than 15% or more than 95% of the
    # image — likely a failed segmentation or a near-uniform image.
    fg_ratio = fg_area / img_area
    if fg_ratio < 0.15 or fg_ratio > 0.95:
        log.info(f"GrabCut fg_ratio={fg_ratio:.2f} outside valid range. Using original.")
        return pil_image, False

    # Scale bounding box back to original resolution
    inv = 1.0 / scale
    x1 = max(0, int((x * inv) - w * 0.05))
    y1 = max(0, int((y * inv) - h * 0.05))
    x2 = min(w, int(((x + bw) * inv) + w * 0.05))
    y2 = min(h, int(((y + bh) * inv) + h * 0.05))

    crop = pil_image.crop((x1, y1, x2, y2))
    cw, ch = crop.size

    # Reject crops that are too small to be useful
    if cw < MIN_CROP_SIZE_PX or ch < MIN_CROP_SIZE_PX:
        log.info(f"GrabCut crop too small ({cw}×{ch}px). Using original.")
        return pil_image, False

    log.info(f"GrabCut crop: ({x1},{y1})→({x2},{y2}), fg_ratio={fg_ratio:.2f}")
    return crop, True


# ================================================================
# STAGE 3 — OOD (OUT-OF-DISTRIBUTION) DETECTION
#
# Computes Shannon entropy of the ensemble's probability outputs.
# A model that recognises its training distribution concentrates
# probability mass on a few classes → low entropy.
# A model that doesn't recognise the input spreads mass nearly
# uniformly across all 38 classes → high entropy.
#
# This runs AFTER GrabCut so landscape images that happen to have
# a plant region extracted still get caught if the crop itself
# doesn't look like a leaf to the model.
#
# Shannon entropy: H = -Σ p_i * log2(p_i)
# Max for 38 classes: log2(38) ≈ 5.25 bits
# ================================================================

def compute_entropy(probs_tensor: torch.Tensor) -> float:
    """Shannon entropy of a probability distribution in bits."""
    p = probs_tensor.squeeze().clamp(min=1e-9)
    return float(-torch.sum(p * torch.log2(p)).item())


def ood_check(vit_probs: torch.Tensor, swin_probs: torch.Tensor) -> tuple[bool, float]:
    """
    Returns (is_ood, avg_entropy).
    Uses average entropy across both models — more stable than
    relying on either model alone, since one model may be more
    confident than the other on certain out-of-distribution inputs.
    """
    vit_h  = compute_entropy(vit_probs)
    swin_h = compute_entropy(swin_probs)
    avg_h  = (vit_h + swin_h) / 2.0
    log.info(f"Entropy — ViT: {vit_h:.3f}, Swin: {swin_h:.3f}, Avg: {avg_h:.3f}")
    return avg_h > OOD_ENTROPY_THRESHOLD, round(avg_h, 3)


# ================================================================
# CONFIDENCE TIER + ADVICE
# ================================================================

def get_confidence_tier(confidence: float) -> str:
    if confidence >= CONFIDENCE_HIGH:
        return "HIGH"
    elif confidence >= CONFIDENCE_MEDIUM:
        return "MEDIUM"
    else:
        return "LOW"


def get_advice(top_class: str, confidence: float, models_agree: bool) -> str:
    tier = get_confidence_tier(confidence)

    if tier == "HIGH" and models_agree:
        return "Both models agree with high confidence. Result is reliable."

    if tier == "HIGH" and not models_agree:
        return (
            "High confidence but models had some disagreement. "
            "Result is likely correct — consider a second photo to confirm."
        )

    if tier == "MEDIUM" and models_agree:
        if top_class in HARD_CLASSES:
            return (
                f"{top_class.replace('___', ' — ')} is a visually subtle condition. "
                "Medium confidence is normal for this class. "
                "Use additional diagnostic methods to confirm."
            )
        return (
            "Medium confidence. Both models agree but are not fully certain. "
            "Try a clearer photo with the leaf isolated against a plain background."
        )

    if tier == "MEDIUM" and not models_agree:
        return (
            "Medium confidence with model disagreement. "
            "Try a closer, clearer photo of the affected leaf area. "
            "Ensure the leaf fills most of the frame."
        )

    if top_class in HARD_CLASSES:
        return (
            f"{top_class.replace('___', ' — ')} is one of the hardest classes to detect visually. "
            "Low confidence is expected. "
            "Consult an agricultural expert or use lab testing to confirm."
        )

    return (
        "Low confidence — the model is uncertain. "
        "Please retake the photo: isolate one leaf, use good lighting, "
        "plain background, and ensure the leaf fills most of the frame."
    )


# ================================================================
# STAGE 4 — ENSEMBLE PREDICT
# ================================================================

def ensemble_predict(image_tensor: torch.Tensor):
    """
    Runs both models, applies dynamic weight shifting, returns
    top-3 results plus full diagnostic information.

    Also returns raw vit_probs and swin_probs so the caller can
    run OOD detection on the same forward pass — no wasted compute.
    """
    with torch.no_grad():
        vit_logits  = vit_model(image_tensor)
        swin_logits = swin_model(image_tensor)

        vit_probs  = F.softmax(vit_logits,  dim=1)
        swin_probs = F.softmax(swin_logits, dim=1)

        vit_conf     = vit_probs.max().item()
        swin_conf    = swin_probs.max().item()
        vit_top_idx  = vit_probs.argmax().item()
        swin_top_idx = swin_probs.argmax().item()
        models_agree = (vit_top_idx == swin_top_idx)

        # ── BRANCH 1: Agreement ──────────────────────────────────
        if models_agree:
            avg_logits = (BASE_WEIGHT_VIT  * vit_logits +
                          BASE_WEIGHT_SWIN * swin_logits)
            strategy   = (f"agreement_blend "
                          f"(vit={BASE_WEIGHT_VIT}, swin={BASE_WEIGHT_SWIN})")

        # ── BRANCH 2: Disagreement — ViT more confident ──────────
        elif vit_conf >= swin_conf:
            avg_logits = (VIT_DOM_WEIGHT_VIT  * vit_logits +
                          VIT_DOM_WEIGHT_SWIN * swin_logits)
            strategy   = (f"vit_dominant "
                          f"(vit={vit_conf:.3f} >= swin={swin_conf:.3f})")

        # ── BRANCH 3: Disagreement — Swin dominantly confident ───
        elif swin_conf > SWIN_DOMINANCE_RATIO * vit_conf:
            avg_logits = (SWIN_DOM_WEIGHT_VIT  * vit_logits +
                          SWIN_DOM_WEIGHT_SWIN * swin_logits)
            strategy   = (f"swin_dominant "
                          f"(swin={swin_conf:.3f} > "
                          f"{SWIN_DOMINANCE_RATIO}x vit={vit_conf:.3f})")

        # ── BRANCH 4: Fallback ───────────────────────────────────
        else:
            avg_logits = (BASE_WEIGHT_VIT  * vit_logits +
                          BASE_WEIGHT_SWIN * swin_logits)
            strategy   = (f"base_weighted_blend "
                          f"(disagreement, gap < {SWIN_DOMINANCE_RATIO}x ratio)")

        final_probs         = F.softmax(avg_logits, dim=1)
        probs               = final_probs.squeeze()
        top3_prob, top3_idx = torch.topk(probs, 3)

    results = [
        {
            "class":      class_names[top3_idx[i].item()],
            "confidence": round(float(top3_prob[i].item()), 4)
        }
        for i in range(3)
    ]

    return (
        results,
        strategy,
        round(vit_conf,  4),
        round(swin_conf, 4),
        models_agree,
        vit_probs,     # raw — passed to OOD check
        swin_probs     # raw — passed to OOD check
    )


# ================================================================
# SHARED IMAGE DECODER
# Runs quality checks + GrabCut before returning the tensor.
# Returns the tensor plus metadata about what was done to the image.
# ================================================================

async def decode_and_prepare(file: UploadFile) -> tuple[torch.Tensor, dict]:
    """
    Full preprocessing pipeline:
      1. Read bytes + file size check
      2. Decode PIL image + dimension check
      3. Blur detection
      4. GrabCut foreground extraction
      5. Transform to tensor

    Returns (tensor, meta) where meta contains all preprocessing
    decisions so they can be surfaced in the API response.
    """
    image_bytes = await file.read()
    check_file_size(image_bytes)

    try:
        pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except UnidentifiedImageError:
        raise HTTPException(
            status_code=422,
            detail="Could not decode image. Please upload a valid JPEG or PNG."
        )

    check_image_dimensions(pil_image)
    blur_score = check_blur(pil_image)

    cropped_image, was_cropped = grabcut_extract(pil_image)

    tensor = transform(cropped_image).unsqueeze(0).to(device)

    meta = {
        "original_size":  list(pil_image.size),
        "blur_score":     round(blur_score, 1),
        "auto_cropped":   was_cropped,
        "crop_size":      list(cropped_image.size) if was_cropped else list(pil_image.size),
    }

    return tensor, meta


# ================================================================
# POST /predict — PRODUCTION ENDPOINT
# ================================================================

@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    """
    Production endpoint.

    Full pipeline:
      image quality checks → GrabCut crop → OOD detection → ensemble

    Response fields:
      predictions             top-3 classes with confidence
      confidence_tier         HIGH / MEDIUM / LOW / REJECTED
      models_agree            bool
      advice                  human-readable guidance
      low_confidence_warning  bool (true when confidence < 0.50)
      ood_rejected            bool (true when image looks non-leaf)
      auto_cropped            bool (true when GrabCut extracted a region)
      latency_ms              end-to-end time in milliseconds
    """
    t_start = time.perf_counter()

    image, meta = await decode_and_prepare(file)

    results, strategy, vit_conf, swin_conf, models_agree, vit_probs, swin_probs = (
        ensemble_predict(image)
    )

    is_ood, entropy = ood_check(vit_probs, swin_probs)

    latency_ms = round((time.perf_counter() - t_start) * 1000, 1)
    log.info(
        f"predict | ood={is_ood} | cropped={meta['auto_cropped']} | "
        f"top={results[0]['class']} @ {results[0]['confidence']:.3f} | "
        f"strategy={strategy} | {latency_ms}ms"
    )

    if is_ood:
        return {
            "predictions":            [],
            "confidence_tier":        "REJECTED",
            "models_agree":           False,
            "advice": (
                "This image does not appear to contain a plant leaf. "
                "Please upload a close-up photo of a single leaf against "
                "a plain background."
            ),
            "low_confidence_warning": True,
            "ood_rejected":           True,
            "ood_entropy":            entropy,
            "auto_cropped":           meta["auto_cropped"],
            "latency_ms":             latency_ms,
        }

    top_class      = results[0]["class"]
    top_confidence = results[0]["confidence"]
    tier           = get_confidence_tier(top_confidence)
    advice         = get_advice(top_class, top_confidence, models_agree)

    return {
        "predictions":            results,
        "confidence_tier":        tier,
        "models_agree":           models_agree,
        "advice":                 advice,
        "low_confidence_warning": top_confidence < CONFIDENCE_MEDIUM,
        "ood_rejected":           False,
        "ood_entropy":            entropy,
        "auto_cropped":           meta["auto_cropped"],
        "latency_ms":             latency_ms,
    }


# ================================================================
# POST /predict/debug — DIAGNOSTIC ENDPOINT
# ================================================================

@app.post("/predict/debug")
async def predict_debug(file: UploadFile = File(...)):
    """
    Full diagnostic endpoint. Returns all internals including:
      - per-model top-3 predictions before fusion
      - active fusion strategy string with live confidence values
      - OOD entropy values per model
      - preprocessing metadata (blur score, crop dimensions)
      - all weight configurations
    """
    t_start = time.perf_counter()

    image, meta = await decode_and_prepare(file)

    # Independent per-model outputs (before fusion)
    with torch.no_grad():
        vit_probs_raw  = F.softmax(vit_model(image),  dim=1).squeeze()
        swin_probs_raw = F.softmax(swin_model(image), dim=1).squeeze()

    def top3_from_probs(probs):
        top_p, top_i = torch.topk(probs, 3)
        return [
            {
                "class":      class_names[top_i[i].item()],
                "confidence": round(float(top_p[i].item()), 4)
            }
            for i in range(3)
        ]

    vit_top3  = top3_from_probs(vit_probs_raw)
    swin_top3 = top3_from_probs(swin_probs_raw)

    results, strategy, vit_conf, swin_conf, models_agree, vit_probs, swin_probs = (
        ensemble_predict(image)
    )

    is_ood, avg_entropy = ood_check(vit_probs, swin_probs)

    top_class      = results[0]["class"]
    top_confidence = results[0]["confidence"]
    tier           = get_confidence_tier(top_confidence)
    advice         = get_advice(top_class, top_confidence, models_agree)

    latency_ms = round((time.perf_counter() - t_start) * 1000, 1)

    return {
        "vit_predictions":      vit_top3,
        "swin_predictions":     swin_top3,
        "ensemble_predictions": results,
        "confidence_tier":      tier,
        "advice":               advice,
        "diagnosis": {
            "models_agree":           models_agree,
            "strategy_used":          strategy,
            "vit_peak_confidence":    vit_conf,
            "swin_peak_confidence":   swin_conf,
            "ood_rejected":           is_ood,
            "ood_entropy":            avg_entropy,
            "ood_threshold":          OOD_ENTROPY_THRESHOLD,
            "ood_entropy_vit":        round(compute_entropy(vit_probs_raw), 3),
            "ood_entropy_swin":       round(compute_entropy(swin_probs_raw), 3),
            "low_confidence_warning": top_confidence < CONFIDENCE_MEDIUM,
            "base_weights":           {"vit": BASE_WEIGHT_VIT,  "swin": BASE_WEIGHT_SWIN},
            "dynamic_weights": {
                "vit_dominant":  {"vit": VIT_DOM_WEIGHT_VIT,  "swin": VIT_DOM_WEIGHT_SWIN},
                "swin_dominant": {"vit": SWIN_DOM_WEIGHT_VIT, "swin": SWIN_DOM_WEIGHT_SWIN},
                "dominance_ratio_gate": SWIN_DOMINANCE_RATIO
            },
        },
        "preprocessing": {
            "original_size":  meta["original_size"],
            "blur_score":     meta["blur_score"],
            "blur_threshold": BLUR_THRESHOLD,
            "auto_cropped":   meta["auto_cropped"],
            "crop_size":      meta["crop_size"],
        },
        "latency_ms": latency_ms,
    }


# ================================================================
# GET /health
# ================================================================

@app.get("/health")
async def health():
    return {
        "status":      "ok",
        "models":      ["vit_b_16", "swin_t"],
        "num_classes": NUM_CLASSES,
        "device":      str(device),
        "thresholds": {
            "ood_entropy":       OOD_ENTROPY_THRESHOLD,
            "blur":              BLUR_THRESHOLD,
            "confidence_high":   CONFIDENCE_HIGH,
            "confidence_medium": CONFIDENCE_MEDIUM,
        }
    }