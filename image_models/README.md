# 🌿 ViT + Swin Transformer Ensemble for Plant Disease Classification

## 📌 Overview

This project implements a high-accuracy plant disease classification system using an ensemble of:

- 🧠 **Vision Transformer (ViT-B/16)**
- 🌊 **Swin Transformer (Swin-Tiny)**

Both models are fine-tuned on the PlantVillage dataset (38 classes) using transfer learning from ImageNet.

The final system is deployed as a FastAPI REST API for real-time prediction.

## 🎯 Objective

To build a transformer-based deep learning system that:

- Classifies 38 plant diseases
- Uses transfer learning from ImageNet
- Combines models using late fusion ensemble
- Achieves >99% accuracy
- Provides deployable REST API inference

## 📊 Dataset

- **Dataset**: PlantVillage
- **Total Images**: 54,305
- **Number of Classes**: 38
- **Image Type**: RGB leaf images
- **Input Resolution**: 224×224

### 🌱 38 Plant Disease Classes

- Apple___Apple_scab
- Apple___Black_rot
- Apple___Cedar_apple_rust
- Apple___healthy
- Blueberry___healthy
- Cherry_(including_sour)__Powdery_mildew
- Cherry(including_sour)___healthy
- Corn_(maize)__Cercospora_leaf_spot Gray_leaf_spot
- Corn(maize)_Common_rust
- Corn(maize)__Northern_Leaf_Blight
- Corn(maize)___healthy
- Grape___Black_rot
- Grape___Esca_(Black_Measles)
- Grape___Leaf_blight_(Isariopsis_Leaf_Spot)
- Grape___healthy
- Orange___Haunglongbing_(Citrus_greening)
- Peach___Bacterial_spot
- Peach___healthy
- Pepper,_bell___Bacterial_spot
- Pepper,_bell___healthy
- Potato___Early_blight
- Potato___Late_blight
- Potato___healthy
- Raspberry___healthy
- Soybean___healthy
- Squash___Powdery_mildew
- Strawberry___Leaf_scorch
- Strawberry___healthy
- Tomato___Bacterial_spot
- Tomato___Early_blight
- Tomato___Late_blight
- Tomato___Leaf_Mold
- Tomato___Septoria_leaf_spot
- Tomato___Spider_mites Two-spotted_spider_mite
- Tomato___Target_Spot
- Tomato___Tomato_Yellow_Leaf_Curl_Virus
- Tomato___Tomato_mosaic_virus
- Tomato___healthy

## 🧠 Model Architecture

### 🔹 Vision Transformer (ViT-B/16)
- Patch-based global self-attention
- Captures long-range spatial dependencies
- Fully fine-tuned

### 🔹 Swin Transformer (Swin-Tiny)
- Hierarchical transformer architecture
- Shifted window attention
- Captures local multi-scale textures
- Fully fine-tuned

### 🔥 Ensemble Method (Late Fusion)
Final prediction is computed as:
`P_final = α * P_ViT + (1 − α) * P_Swin`

Where:
`α = 0.5`

This balances global structural understanding (ViT) and local texture detection (Swin).

## ⚙️ Training Configuration

| Parameter | Value |
|-----------|-------|
| Optimizer | AdamW |
| Loss Function | CrossEntropyLoss |
| Learning Rate (ViT) | 3e-5 |
| Learning Rate (Swin) | 1e-4 |
| Transfer Learning | ImageNet Pretrained |
| Fine-Tuning | Full model |

## 📈 Final Evaluation Results

| Model | Test Accuracy |
|-------|---------------|
| Vision Transformer (ViT-B/16) | 99.59% |
| Swin Transformer (Swin-Tiny) | ~99.7% |
| ViT + Swin Ensemble | ~99.8% |

## 🚀 Deployment (FastAPI)

### 🔹 Install Dependencies
```bash
pip install -r requirements.txt
```

### 🔹 Download Model Weights
Due to GitHub file size limits (>100MB), download model weights from:
- **ViT Model**: [Paste Google Drive Link]
- **Swin Model**: [Paste Google Drive Link]

Place them inside:
`models/`

### 🔹 Run the API
```bash
uvicorn app.main:app --reload
```

Open in browser:
http://127.0.0.1:8000/docs

Upload a plant leaf image to receive prediction and confidence score.

## 🛠 Tech Stack

- Python 3.11
- PyTorch
- Torchvision
- FastAPI
- Uvicorn
- Scikit-Learn
- Matplotlib
- Seaborn

## 👨‍🎓 Author
**Hariprasanth U**  
*Transformer-Based Plant Disease Classification*
