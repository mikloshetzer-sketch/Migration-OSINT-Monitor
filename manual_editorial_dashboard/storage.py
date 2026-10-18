"""GitHub private repository JSON storage, server-side token only."""
import json
import base64
import os
import requests

class StoreError(RuntimeError): pass

class GitHubStore:
    def __init__(self):
        self.repo = os.environ.get('EDITORIAL_PRIVATE_REPO', '').strip()
        self.token = os.environ.get('EDITORIAL_GITHUB_TOKEN', '').strip()
        if not self.repo or '/' not in self.repo or not self.token:
            raise StoreError('Hiányzik EDITORIAL_PRIVATE_REPO vagy EDITORIAL_GITHUB_TOKEN.')
        self.base = f'https://api.github.com/repos/{self.repo}/contents/'
        self.headers = {'Authorization': f'Bearer {self.token}', 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}

    def read(self, path, default=None):
        response = requests.get(self.base+path, headers=self.headers, timeout=25)
        if response.status_code == 404: return default, None
        if not response.ok: raise StoreError(f'GitHub olvasási hiba ({response.status_code}): {response.text[:250]}')
        result=response.json()
        if result.get('type')!='file': raise StoreError('A megadott útvonal nem fájl.')
        raw=base64.b64decode(result['content'].replace('\n',''))
        return json.loads(raw.decode('utf-8')), result['sha']

    def write(self, path, value, sha=None):
        payload={'message':f'Editorial review: {path}', 'content':base64.b64encode((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()).decode()}
        if sha: payload['sha']=sha
        response=requests.put(self.base+path,headers=self.headers,json=payload,timeout=30)
        if response.status_code in (409,422): raise StoreError('Ütköző mentés: közben megváltozott a fájl. Frissítsd az oldalt, majd ismételd meg.')
        if not response.ok: raise StoreError(f'GitHub mentési hiba ({response.status_code}): {response.text[:250]}')
        return response.json()
