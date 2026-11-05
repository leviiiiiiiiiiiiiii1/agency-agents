import { STORAGE_KEY, hydrate, defaultData } from './defaults';
import type { AppData } from '../types';

export function loadData(): AppData {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultData();
    return hydrate(JSON.parse(raw));
  } catch (e) {
    console.warn('Não foi possível ler os dados salvos, usando configuração limpa.', e);
    return defaultData();
  }
}

export function saveData(data: AppData): { ok: boolean; error?: string } {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    return { ok: true };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, error: msg };
  }
}

export function wipeData() {
  localStorage.removeItem(STORAGE_KEY);
  for (const k of Object.keys(localStorage)) {
    if (k.startsWith('tcc:')) localStorage.removeItem(k);
  }
}

export function download(filename: string, content: BlobPart, mime = 'application/json') {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Reduz uma screenshot a uma miniatura JPEG leve antes de guardar no localStorage. */
export async function compressImage(file: File, maxSide = 900, quality = 0.72): Promise<string> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result));
    fr.onerror = reject;
    fr.readAsDataURL(file);
  });
  return new Promise<string>((resolve) => {
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(img.width * scale));
      canvas.height = Math.max(1, Math.round(img.height * scale));
      const ctx = canvas.getContext('2d');
      if (!ctx) return resolve(dataUrl);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      resolve(canvas.toDataURL('image/jpeg', quality));
    };
    img.onerror = () => resolve(dataUrl);
    img.src = dataUrl;
  });
}
