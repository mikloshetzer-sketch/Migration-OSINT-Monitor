"""Private Google-OIDC Streamlit app. Deploy on a server supporting Streamlit st.login."""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
import streamlit as st
from core import collect
from storage import GitHubStore, StoreError

TZ=ZoneInfo('Europe/Budapest')
st.set_page_config(page_title='Migration OSINT | Privát szerkesztő',page_icon='🛡️',layout='wide')
st.title('Migration OSINT – Manuális szerkesztői dashboard')
st.caption('Kizárólag egy kiválasztott nap · eredeti poszt és magyar fordítás · auditált döntések')

# Fail closed: never display any data until Google OIDC has verified the session.
if not hasattr(st,'user') or not st.user.is_logged_in:
    st.info('A felület használatához jelentkezz be az engedélyezett Google-fiókkal.')
    if st.button('Bejelentkezés Google-fiókkal'):st.login('google')
    st.stop()

allowed=os.environ.get('EDITORIAL_ALLOWED_EMAIL','').strip().lower()
email=str(st.user.get('email','')).strip().lower()
verified=st.user.get('email_verified',False)
if not allowed or email!=allowed or verified not in (True,'true','True'):
    st.error('Nincs jogosultságod a szerkesztői felülethez.')
    if st.button('Kijelentkezés'):st.logout()
    st.stop()

with st.sidebar:
    st.success('Azonosított szerkesztő')
    st.caption(email)
    if st.button('Kijelentkezés'):st.logout()

try:store=GitHubStore()
except StoreError as exc:
    st.error(str(exc));st.stop()

selected=st.date_input('Ellenőrzendő nap',value=datetime.now(TZ).date()-timedelta(days=1),max_value=datetime.now(TZ).date(),format='YYYY-MM-DD')
day=selected.isoformat()
# Data is stored in a PRIVATE repository, not GitHub Pages.
# Each archive contains pre-AI-filter records for one collection day.
try:
    data,_=store.read(f'archive/{day}.json',default=None)
    overrides,sha=store.read(f'reviews/{day}.json',default={'schema_version':1,'date':day,'decisions':{}})
except StoreError as exc:
    st.error(str(exc));st.stop()

if data is None:
    st.warning('Erre a napra még nincs privát nyersarchívum. A nyilvános dashboardból a kiszűrt rekordok nem állíthatók teljes körűen vissza.')
    st.stop()

entries=collect(data,selected)
if not isinstance(overrides.get('decisions'),dict):st.error('Hibás döntési napló.');st.stop()
reviewed=sum(e['key'] in overrides['decisions'] for e in entries)
a,b,c=st.columns(3)
a.metric('Rekordok',len(entries));b.metric('Ellenőrizve',reviewed);c.metric('Hátralévő',len(entries)-reviewed)

@st.cache_data(show_spinner=False,ttl=86400)
def translate(text):
    token=os.environ.get('OPENAI_API_KEY','')
    if not token:raise RuntimeError('A fordításhoz OPENAI_API_KEY szükséges.')
    resp=requests.post('https://api.openai.com/v1/chat/completions',headers={'Authorization':f'Bearer {token}'},json={'model':os.environ.get('EDITORIAL_TRANSLATION_MODEL','gpt-4.1-mini'),'temperature':0,'messages':[{'role':'system','content':'Translate faithfully into Hungarian. Do not verify, infer, add or remove claims. Keep dates, numbers and uncertainty.'},{'role':'user','content':text[:16000]}]},timeout=75)
    resp.raise_for_status()
    return resp.json()['choices'][0]['message']['content']

for entry in entries:
    r=entry['record'];key=entry['key'];prev=overrides['decisions'].get(key,{})
    txt=str(r.get('text') or r.get('representative_text') or r.get('content') or r.get('description') or '')
    with st.expander(f"{key} · {r.get('event_type') or r.get('title') or 'Esemény'} · {'✓' if prev else '○'}"):
        st.caption(f"Gyűjtés: {r.get('collected_at') or r.get('created_at') or r.get('first_detected_at') or r.get('first_seen') or '-'} · AI: {r.get('ai_editorial_decision','nincs')}")
        st.text_area('Eredeti nyelvű poszt / esemény',txt,disabled=True,height=160,key='original-'+key)
        url=r.get('source_url') or r.get('url')
        if isinstance(url,str) and url.startswith(('https://','http://')):st.link_button('Eredeti forrás',url)
        if st.button('Magyar fordítás',key='translate-'+key):
            try:st.session_state['hu-'+day+'-'+key]=translate(txt)
            except Exception as exc:st.error(f'Fordítási hiba: {exc}')
        hu=st.session_state.get('hu-'+day+'-'+key)
        if hu:st.text_area('Magyarul (gépi fordítás)',hu,disabled=True,height=160,key='translated-'+key)
        with st.form('review-'+day+'-'+key):
            options=['PUBLISH','REVIEW','EXCLUDE']
            d=st.selectbox('Szerkesztői döntés',options,index=options.index(prev['decision']) if prev.get('decision') in options else 1)
            loc=st.text_input('Helyszín javítása',value=prev.get('location',''))
            typ=st.text_input('Eseménytípus javítása',value=prev.get('event_type',''))
            summary=st.text_area('Magyar összefoglaló / javítás',value=prev.get('summary_hu',''))
            note=st.text_area('Indoklás (kötelező)',value=prev.get('note',''))
            save=st.form_submit_button('Döntés mentése')
        if save:
            if not note.strip():st.error('Adj meg indoklást.')
            else:
                # Optimistic concurrency: no silent overwrite of another save.
                new=dict(overrides)
                new['decisions']=dict(overrides['decisions'])
                new['decisions'][key]={'decision':d,'note':note.strip(),'location':loc.strip(),'event_type':typ.strip(),'summary_hu':summary.strip(),'reviewed_by':email,'reviewed_at':datetime.now(TZ).isoformat(),'original_ai_decision':r.get('ai_editorial_decision'),'source_url':url,'record_id':key}
                try:store.write(f'reviews/{day}.json',new,sha);st.success('GitHubra mentve.');st.rerun()
                except StoreError as exc:st.error(str(exc))

st.caption('A mentések privát GitHub-repóba kerülnek. A nyilvános monitorra történő alkalmazás külön, ellenőrzött publikációs lépés.')
