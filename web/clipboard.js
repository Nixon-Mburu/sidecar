// Clipboard image support is most portable with actual PNG bytes.
async function pngBlob(file) {
  const bitmap = await createImageBitmap(file);
  const canvas = document.createElement('canvas');
  try {
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Image conversion is unavailable.');
    context.drawImage(bitmap, 0, 0);
    return await new Promise((resolve, reject) => {
      canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Image conversion failed.')), 'image/png');
    });
  } finally {
    bitmap.close();
    canvas.width = canvas.height = 0;
  }
}

export function copyImage(file) {
  if (typeof ClipboardItem !== 'function' || typeof navigator.clipboard?.write !== 'function') {
    return Promise.reject(new Error('Image copying is unavailable in this browser. Use the share icon.'));
  }
  // Start the clipboard write during the click; conversion resolves its payload later.
  return navigator.clipboard.write([new ClipboardItem({ 'image/png': pngBlob(file) })]);
}
