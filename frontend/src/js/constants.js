// Centralized constants and thresholds
export const MODEL_URL = "models/model_24.tflite"; // path to tflite model relative to public/

// Backend API base URL
export const BACKEND_URL = (typeof window !== 'undefined' && window.BACKEND_URL) || (location.origin + '/api');

// Offscreen crop size for embeddings
export const CROP_SIZE = 224; // MobileNet input size

// Matching settings
export const COSINE_THRESHOLD = 0.55; // tune as needed [0..1]
export const DEBUG_FALLBACK_CROP = false; // try center crop when no detections (debug only)

// Rendering limits
export const MAX_BOXES_PER_FRAME = 1; // limit number of boxes drawn per frame
export const MIN_BOX_SCORE = 0.50; // min category score to draw a box/attempt match

export let RADIUS_KM = 0.3;   // fallback
export let CITY_NAME = "Forlì";  // fallback

export async function loadServerConfig() {
  try {
    const res = await fetch(`${BACKEND_URL}/config`);
    const cfg = await res.json();

    if (cfg.RADIUS_KM !== undefined) RADIUS_KM = cfg.RADIUS_KM;
    if (cfg.CITY_NAME !== undefined) CITY_NAME = cfg.CITY_NAME;

    console.log("Loaded config:", cfg);
  } catch (e) {
    console.warn("Could not load server config, using defaults", e);
  }
}