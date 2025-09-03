import { CROP_SIZE } from './constants.js';
import { videoEl } from './dom.js';

let embedModel = null; // MobileNet feature extractor
let runtimeDim = null;

// Offscreen canvas for crops
const cropCanvas = document.createElement('canvas');
cropCanvas.width = cropCanvas.height = CROP_SIZE;
const cropCtx = cropCanvas.getContext('2d', { willReadFrequently: true });

export async function initEmbeddingModel() {
  const tf = globalThis.tf;
  const mobilenetGlobal = globalThis.mobilenet;
  if (!tf) throw new Error('TensorFlow.js non caricato');
  try { await tf.setBackend('webgl'); } catch {}
  await tf.ready();
  if (!mobilenetGlobal) throw new Error('MobileNet non caricato');
  embedModel = await mobilenetGlobal.load({ version: 2, alpha: 1.0 });
  // Warmup to detect runtime dimension
  try {
    tf.tidy(() => {
      const dummy = tf.zeros([224, 224, 3]);
      const emb = embedModel.infer(dummy, true);
      runtimeDim = emb.size;
    });
    console.log('MobileNet ready, backend:', tf.getBackend(), 'runtimeDim:', runtimeDim);
  } catch (e) {
    console.warn('MobileNet warmup failed:', e);
  }
}

export function hasEmbedModel() {
  return !!embedModel;
}

export function getRuntimeDim() {
  return runtimeDim;
}

export function ensureRuntimeDim() {
  try {
    const tf = globalThis.tf;
    if (!tf || !embedModel) return;
    if (runtimeDim == null) {
      tf.tidy(() => {
        const dummy = tf.zeros([224, 224, 3]);
        const emb = embedModel.infer(dummy, true);
        runtimeDim = emb.size;
      });
    }
  } catch (e) {
    console.warn('ensureRuntimeDim error:', e);
  }
}

function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }

export function cropToCanvasFromVideo(box) {
  const vx = clamp(box.originX, 0, videoEl.videoWidth);
  const vy = clamp(box.originY, 0, videoEl.videoHeight);
  const vw = clamp(box.width, 1, videoEl.videoWidth - vx);
  const vh = clamp(box.height, 1, videoEl.videoHeight - vy);
  cropCtx.clearRect(0, 0, CROP_SIZE, CROP_SIZE);
  cropCtx.drawImage(videoEl, vx, vy, vw, vh, 0, 0, CROP_SIZE, CROP_SIZE);
  return cropCanvas;
}

export function embedFromCanvas(can) {
  const tf = globalThis.tf;
  if (!tf || !embedModel) throw new Error('Embedding model non disponibile');
  // Use TypedArray and normalize in-place to avoid GC and spread overhead
  const out = tf.tidy(() => {
    const input = tf.browser.fromPixels(can);            // [224,224,3]
    const feat = embedModel.infer(input, true).flatten(); // Tensor1D [D]
    return feat.dataSync(); // Float32Array
  });
  let sum = 0.0;
  for (let i = 0; i < out.length; i++) sum += out[i] * out[i];
  const inv = sum > 0 ? 1 / Math.sqrt(sum) : 1.0;
  if (inv !== 1.0) {
    for (let i = 0; i < out.length; i++) out[i] *= inv;
  }
  return out; // Float32Array
}

export function cosineSim(vecA, vecB) {
  if (!vecA || !vecB || vecA.length !== vecB.length) return -1;
  let dot = 0;
  for (let i = 0; i < vecA.length; i++) dot += vecA[i] * vecB[i];
  return dot;
}
