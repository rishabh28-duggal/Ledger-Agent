// Apply the saved appearance before styles paint; no account or document data.
try {
 const saved=localStorage.getItem('ledger-theme');
 document.documentElement.dataset.theme=saved==='dark'||(!saved&&matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light';
} catch {}
