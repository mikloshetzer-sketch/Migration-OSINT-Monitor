Migration OSINT – privát napi nyersarchiválás (1. szakasz)
Feltöltés – kizárólag a NYILVÁNOS `Migration-OSINT-Monitor` repóba
`publish_private_editorial_archive.py` → `analysis/publish_private_editorial_archive.py` (új fájl).
`manual-run.yml` → `.github/workflows/manual-run.yml` (a meglévő teljes fájl cseréje).
GitHub → nyilvános repo → Settings → Secrets and variables → Actions → New repository secret:
Name: `EDITORIAL_GITHUB_TOKEN`
Secret: a korábban elkészített, kizárólag a privát repo `Contents: Read and write` jogosultságú token. Ne küldd el senkinek, és ne commitold.
GitHub → Actions → Migration OSINT Monitor → Run workflow.
Ellenőrzés: a futásban `Archive pre-AI-gate records to PRIVATE repository` lépés legyen zöld. A privát repo `archive/YYYY-MM-DD.json` fájljai jelenjenek meg.
Mit csinál?
A meglévő export és történeti tisztítás UTÁN, de az AI Editorial Gate ELŐTT a napi, időbélyeges rekordokat az egyetlen privát repóba menti. A rekordokat eredeti tartalommal, forrás-szekciónként, növekményesen archiválja. Már elmentett rekordot nem ír felül. A szerkesztői `app.py` által várt napi JSON formátumot használja. Időbélyeg vagy rekordazonosító nélküli tételeket kihagy és a naplóban számlálja. Az archívum a történeti tisztítás utáni állapotot őrzi, tehát nem teljes nyers adatbázis-export.
A GitHub Actions hiba esetén leáll az AI-gate előtt, nem publikál úgy, hogy az archiválás sikertelen volt. Az első futás után a privát repóban az `archive` könyvtár létrejön. Ha a token lejár, újra kell állítani.
Amihez NEM nyúl
`analysis/ai_editorial_gate.py` és az AI 2026-10-17-es határa
Source Intelligence logika és fájlok
A nyilvános dashboard megjelenítése
Kézi döntések automatikus visszaírása: ez a következő, külön ellenőrizendő szakasz
Fontos korlát
A `core.py` a dátumot `collected_at` / `first_collected_at` / `first_detected_at` / `created_at` / `first_seen` mezők alapján határozza meg, Budapest időzónában. A különböző források azonosítóinak egyezése az AI gate-tel további validálást igényel a kézi döntések automatikus alkalmazása előtt. A már a monitor exportjából hiányzó történeti rekordok nem állíthatók vissza ezzel a kóddal.
