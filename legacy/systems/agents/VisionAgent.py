from .tools.vision_utils import analyze_image
from .tools.vision_utils import detect_problem_from_image_and_text, is_low_confidence_response
from .tools.vision_utils import retry_problem_detection
from .tools.vision_utils import scan_image_features



def vision_extract_info(state):
    if state.get("text_only_mode"):
        return {**state, "appliance_info": "No image provided - running in text-only mode"}
    
    if not state.get("image_path"):
        return {**state, "appliance_info": "No image path provided"}
        
    appliance_info = analyze_image(state["image_path"])
    return {**state, "appliance_info": appliance_info}



def vision_detect_problem(state):
    if state.get("text_only_mode"):
        return {
            **state,
            "diagnosis": "No image analysis available - proceeding with text-based diagnosis",
            "fallback_triggered": True
        }
    
    if not state.get("image_path"):
        return {
            **state,
            "diagnosis": "No image path provided - proceeding with text-based diagnosis",
            "fallback_triggered": True
        }
    
    diagnosis = detect_problem_from_image_and_text(
        state["image_path"],
        state["text_description"],
        state.get("appliance_info", ""),
        state.get("extracted_features", "")
    )
    fallback = is_low_confidence_response(diagnosis)
    return {
        **state,
        "diagnosis": diagnosis,
        "fallback_triggered": fallback
    }



def vision_fallback(state):
    if state.get("text_only_mode"):
        return {**state, "diagnosis": "No image available for retry - proceeding with text-based analysis"}
    
    if not state.get("image_path"):
        return {**state, "diagnosis": "No image path provided - proceeding with text-based analysis"}
    
    retry = retry_problem_detection(state["image_path"], state["text_description"])
    return {**state, "diagnosis": retry}

def vision_scan_features(state):
    if state.get("text_only_mode"):
        return {**state, "extracted_features": "No image features available - running in text-only mode"}
    
    if not state.get("image_path"):
        return {**state, "extracted_features": "No image path provided"}
    
    extracted_features = scan_image_features(state["image_path"])
    return {**state, "extracted_features": extracted_features}
