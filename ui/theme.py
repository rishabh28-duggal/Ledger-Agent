"""Ledger design tokens. No generated Streamlit class selectors."""
import streamlit as st

CSS = """
<style>
:root {--page:#F5F6F8;--surface:#FFFFFF;--border:#DDE1E7;--control:#7C8795;
--ink:#1B2430;--muted:#5B6675;--accent:#1F4E79;--ready:#1E7A4C;--ready-bg:#E6F3EB;
--review:#9A6200;--review-bg:#FBF0DA;--blocked:#B3261E;--blocked-bg:#FBE7E5;
--neutral:#4A5568;--neutral-bg:#EBEEF2;}
html,body,[data-testid="stApp"] {background:var(--page);color:var(--ink);font-family:'IBM Plex Sans',system-ui,'Segoe UI',Roboto,sans-serif;font-size:16px;line-height:1.5;}
[data-testid="stSidebar"] {background:var(--surface);border-right:1px solid var(--border);}
[data-testid="stMainBlockContainer"] {max-width:1440px;padding-top:2rem;}
h1 {font-size:28px!important;} h2 {font-size:20px!important;} h3 {font-size:20px!important;}
p {max-width:75ch;} label p {font-size:16px!important;} input,textarea {font-size:16px!important;} [data-testid="stCaptionContainer"] {color:var(--muted);font-size:14px;}
button {min-height:36px;border-radius:5px!important;box-shadow:none!important;}
button[kind="primary"] {background:var(--accent);border-color:var(--accent);color:white;}
input,textarea,[data-baseweb="select"]>div {border-color:var(--control)!important;}
a {color:var(--accent);} :is(button,a,input,textarea,select,[tabindex]):focus-visible {outline:2px solid var(--accent)!important;outline-offset:3px!important;}
.ledger-pill {display:inline-flex;align-items:center;gap:8px;padding:4px 10px;border-radius:5px;font-weight:600;font-size:16px;}
.ready {color:var(--ready);background:var(--ready-bg);} .review {color:var(--review);background:var(--review-bg);} .blocked {color:var(--blocked);background:var(--blocked-bg);} .neutral {color:var(--neutral);background:var(--neutral-bg);}
.decision {border-left:4px solid currentColor;padding:16px 20px;margin:12px 0 20px;border-radius:0 6px 6px 0;}
.decision p {margin:8px 0 0;} .amount {font-variant-numeric:tabular-nums;font-family:'IBM Plex Mono',monospace;text-align:right;font-size:28px;}
.wordmark {font-weight:600;font-size:28px;letter-spacing:-1px;margin-bottom:24px;}
.finding {padding:16px 0;border-bottom:1px solid var(--border);} .finding strong {font-size:16px;}
.compare {display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:12px 0;} .compare span {display:block;color:var(--muted);font-size:14px;} .compare b {overflow-wrap:anywhere;font-variant-numeric:tabular-nums;}
.timeline {border-left:2px solid var(--control);padding:0 0 20px 20px;margin-left:8px;} .timeline p {margin:0;} .timeline small {font-size:14px;color:var(--muted);}
.stage {padding:8px 0;font-size:16px;border-bottom:1px solid var(--border);} .stage span {display:inline-block;min-width:90px;font-weight:600;}
.evidence {overflow:auto;} .evidence table {width:100%;border-collapse:collapse;font-size:16px;} .evidence th,.evidence td {padding:10px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top;min-width:100px;} .evidence .uncertain {background:var(--review-bg);} .evidence caption {text-align:left;color:var(--muted);padding-bottom:8px;}
@media(max-width:640px) {button,input,[data-baseweb="select"]>div {min-height:44px!important;} [data-testid="stMainBlockContainer"] {padding:1rem;} .compare {grid-template-columns:1fr;} .amount {text-align:left;} }
@media(prefers-reduced-motion:reduce) {*,*::before,*::after {animation:none!important;transition:none!important;scroll-behavior:auto!important;}}
</style>
"""

def apply_theme():
    st.html(CSS)
