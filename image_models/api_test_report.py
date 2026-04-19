"""
Final API Test Execution Script
Tests the running FastAPI instance locally across downloaded images.
"""
import os
import requests
import json
import time

TEST_IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_images")
API_BASE = "http://127.0.0.1:8000"
REPORT_OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_results.json")

# Map safe filenames back to exact model classes
CLASS_MAP = {
    "Apple___Apple_scab": "Apple___Apple_scab",
    "Apple___Black_rot": "Apple___Black_rot",
    "Apple___Cedar_apple_rust": "Apple___Cedar_apple_rust",
    "Apple___healthy": "Apple___healthy",
    "Corn_maize___Common_rust_": "Corn_(maize)___Common_rust_",
    "Corn_maize___healthy": "Corn_(maize)___healthy",
    "Grape___Black_rot": "Grape___Black_rot",
    "Grape___healthy": "Grape___healthy",
    "Orange___Haunglongbing_Citrus_greening": "Orange___Haunglongbing_(Citrus_greening)",
    "Potato___Early_blight": "Potato___Early_blight",
    "Potato___Late_blight": "Potato___Late_blight",
    "Squash___Powdery_mildew": "Squash___Powdery_mildew",
    "Strawberry___Leaf_scorch": "Strawberry___Leaf_scorch",
    "Tomato___Bacterial_spot": "Tomato___Bacterial_spot",
    "Tomato___Leaf_Mold": "Tomato___Leaf_Mold",
    "Tomato___healthy": "Tomato___healthy",
}

def check_server():
    try:
        requests.get(f"{API_BASE}/docs", timeout=5)
        return True
    except:
        return False

def test_api():
    if not check_server():
        print("ERROR: API is not running at", API_BASE)
        return

    results = []
    
    files = [f for f in os.listdir(TEST_IMAGES_DIR) if f.endswith(".jpg")]
    for f in files:
        # Only test our target classes downloaded from Github
        base_name = f[:-4]
        if base_name not in CLASS_MAP:
            continue
            
        expected_class = CLASS_MAP[base_name]
        filepath = os.path.join(TEST_IMAGES_DIR, f)
        
        print(f"Testing {expected_class}...")
        
        try:
            # Test /predict
            with open(filepath, "rb") as file_obj:
                start = time.time()
                resp = requests.post(f"{API_BASE}/predict", files={"file": (f, file_obj, "image/jpeg")}, timeout=10)
                predict_time = (time.time() - start) * 1000
                resp.raise_for_status()
                predict_data = resp.json()
            
            # Test /predict/debug
            with open(filepath, "rb") as file_obj:
                start = time.time()
                resp_debug = requests.post(f"{API_BASE}/predict/debug", files={"file": (f, file_obj, "image/jpeg")}, timeout=10)
                debug_time = (time.time() - start) * 1000
                resp_debug.raise_for_status()
                debug_data = resp_debug.json()
                
            predicted_class = predict_data["predictions"][0]["class"]
            
            res = {
                "file": f,
                "expected_class": expected_class,
                "predicted_class": predicted_class,
                "is_correct": expected_class == predicted_class,
                "predict_endpoint": {
                    "data": predict_data,
                    "time_ms": predict_time
                },
                "debug_endpoint": {
                    "data": debug_data,
                    "time_ms": debug_time
                }
            }
            results.append(res)
            print(f"  Expected: {expected_class} | Got: {predicted_class} | Match: {res['is_correct']}")
            
        except Exception as e:
            print(f"  Error testing {f}: {e}")

    with open(REPORT_OUTPUT, "w") as out:
        json.dump(results, out, indent=2)
        
    print(f"Done. Tested {len(results)} images. Saved to {REPORT_OUTPUT}")

if __name__ == "__main__":
    test_api()
