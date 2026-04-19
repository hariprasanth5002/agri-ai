import torch
import torch.nn as nn
import torchvision.models as models
import torch.nn.functional as F
from PIL import Image
import torchvision.transforms as transforms

device = torch.device("cpu")

# ── Load models ──────────────────────────────────────────────
vit = models.vit_b_16(weights=None)
vit.heads.head = nn.Linear(vit.heads.head.in_features, 38)
vit.load_state_dict(torch.load("models/best_model.pth", map_location=device))
vit.eval()

swin = models.swin_t(weights=None)
swin.head = nn.Linear(swin.head.in_features, 38)
swin.load_state_dict(torch.load("models/swin-model.pth", map_location=device))
swin.eval()

# ── Load your exact test image ────────────────────────────────
transform = transforms.Compose([
    transforms.Resize((256, 256)),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
])

img = Image.open(r"C:\Users\LENOVO\Downloads\0007ca44-b81d-475c-b8b5-c226a041f020___RS_HL 6331.jpeg").convert("RGB")  # ← your actual file
tensor = transform(img).unsqueeze(0)

# ── Print raw logits BEFORE softmax ──────────────────────────
with torch.no_grad():
    vit_logits  = vit(tensor)
    swin_logits = swin(tensor)

print("ViT  raw logits min/max/mean:",
      round(vit_logits.min().item(),  3),
      round(vit_logits.max().item(),  3),
      round(vit_logits.mean().item(), 3))

print("Swin raw logits min/max/mean:",
      round(swin_logits.min().item(),  3),
      round(swin_logits.max().item(),  3),
      round(swin_logits.mean().item(), 3))

# ── Top 5 with class names ────────────────────────────────────
import json
with open("classes.json") as f:
    class_names = json.load(f)

for name, logits in [("ViT", vit_logits), ("Swin", swin_logits)]:
    probs = F.softmax(logits, dim=1).squeeze()
    top5_p, top5_i = torch.topk(probs, 5)
    print(f"\n{name} top 5:")
    for i in range(5):
        print(f"  {class_names[top5_i[i].item()]:<45} {top5_p[i].item():.4f}")