# Vigorous Multimodal API Testing Report

This report thoroughly tests the `/multimodal` endpoint using all possible combinations of inputs: Text, Voice, and Image.

| Test Scenario | Status | Latency | Intent | Fast Path? | Whisper Transcript | Response Snippet (First 100 char) |
|---|---|---:|---|---:|---|---|
| [🟢 TEXT ONLY - WEATHER] | ✅ SUCCESS (200) | 6.5s | `weather_effect` | False | _N/A_ | - Diagnosis: The current weather in Mumbai is not provided, but the given location is Chennai, which... |
| [🟢 TEXT ONLY - OUT OF SCOPE] | ✅ SUCCESS (200) | 3.87s | `out_of_scope` | True | _N/A_ | I'm happy to help, but I only support topics related to agriculture. I can assist with questions on ... |
| [🟢 TEXT ONLY - RAG DIAGNOSIS] | ✅ SUCCESS (200) | 4.75s | `general_query` | False | _N/A_ | - Diagnosis: The brown spots and rings on your tomato leaves are likely a sign of a fungal disease, ... |
| [📸 IMAGE ONLY] | ✅ SUCCESS (200) | 5.13s | `image_only` | False | _N/A_ | - Diagnosis: Unable to determine without more information. - Treatment: Consult a local agricultural... |
| [📸 TEXT + IMAGE] | ✅ SUCCESS (200) | 7.83s | `crop_management` | False | _N/A_ | - Diagnosis: The provided information is insufficient to determine the exact disease or condition af... |
| [🎤 VOICE ONLY] | ❌ FAILED (500) | 2.58s | `N/A` | N/A | _N/A_ | {"detail":"Processing failed. Please try again."} |
| [🎤 VOICE + 📸 IMAGE] | ❌ FAILED (500) | 2.53s | `N/A` | N/A | _N/A_ | {"detail":"Processing failed. Please try again."} |
| [🎤 VOICE + 📸 IMAGE + 📝 TEXT (FULL MULTIMODAL)] | ❌ FAILED (500) | 2.6s | `N/A` | N/A | _N/A_ | {"detail":"Processing failed. Please try again."} |