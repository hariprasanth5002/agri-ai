"""
Download PlantVillage images using GitHub API to get real filenames.
"""
import os
import requests
import json
import time

TEST_IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_images")
os.makedirs(TEST_IMAGES_DIR, exist_ok=True)

# Target classes we want to download one image each for
TARGET_CLASSES = [
    "Apple___Apple_scab",
    "Apple___Black_rot",
    "Apple___Cedar_apple_rust",
    "Apple___healthy",
    "Corn_(maize)___Common_rust_",
    "Corn_(maize)___healthy",
    "Grape___Black_rot",
    "Grape___healthy",
    "Orange___Haunglongbing_(Citrus_greening)",
    "Potato___Early_blight",
    "Potato___Late_blight",
    "Squash___Powdery_mildew",
    "Strawberry___Leaf_scorch",
    "Tomato___Bacterial_spot",
    "Tomato___Leaf_Mold",
    "Tomato___healthy",
]

GITHUB_API_BASE = "https://api.github.com/repos/spMohanty/PlantVillage-Dataset/contents/raw/color"
headers = {"Accept": "application/vnd.github.v3+json"}


def get_first_image_url(class_name):
    """Get the download_url of the first image in a class directory."""
    url = f"{GITHUB_API_BASE}/{requests.utils.quote(class_name)}?ref=master"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        files = resp.json()
        # Get the first JPG/JPEG/PNG file
        for f in files[:3]:  # just check first 3
            if f.get("download_url") and f["name"].lower().endswith((".jpg", ".jpeg", ".png")):
                return f["download_url"], f["name"]
    except Exception as e:
        print(f"    API error for {class_name}: {e}")
    return None, None


def download_file(url, filepath):
    """Download a file from a URL."""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
        return True
    except Exception as e:
        print(f"    Download error: {e}")
        return False


def main():
    print("=" * 60)
    print("  Downloading PlantVillage images via GitHub API")
    print("=" * 60)
    
    downloaded = 0
    
    for class_name in TARGET_CLASSES:
        safe_name = class_name.replace(" ", "_").replace(",", "").replace("(", "").replace(")", "")
        filepath = os.path.join(TEST_IMAGES_DIR, f"{safe_name}.jpg")
        
        if os.path.exists(filepath) and os.path.getsize(filepath) > 10000:
            print(f"  ✓ Already have: {class_name}")
            downloaded += 1
            continue
        
        print(f"  Fetching: {class_name}...")
        dl_url, filename = get_first_image_url(class_name)
        
        if dl_url:
            if download_file(dl_url, filepath):
                size_kb = os.path.getsize(filepath) / 1024
                print(f"    ✓ Downloaded ({size_kb:.1f} KB)")
                downloaded += 1
            else:
                print(f"    ✗ Failed to download file")
        else:
            print(f"    ✗ Could not find image URL")
        
        # Rate limit: GitHub allows 60 req/hr for unauthenticated
        time.sleep(1)
    
    print(f"\n  Result: {downloaded}/{len(TARGET_CLASSES)} images ready")
    print(f"  Location: {TEST_IMAGES_DIR}")


if __name__ == "__main__":
    main()
