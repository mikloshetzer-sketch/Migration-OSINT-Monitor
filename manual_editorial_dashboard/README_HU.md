Migration OSINT – privát szerkesztői dashboard v2
Fontos: privát üzemeltetés
A GitHub Pages nem futtat Streamlit/Python alkalmazást. A repó csak a forráskódot tárolja. Olyan HTTPS-es Streamlit-futtatókörnyezet szükséges, amely támogatja a Google OIDC-t és a hozzáférésvédelmet. A Google-belépés nem helyettesíti a hálózati/hosting oldali privát elérést; nyilvános alkalmazáscímen a belépőoldal látható lehet, de az adatokhoz nem szabad hozzáférni belépés nélkül.
Szükséges szerveroldali környezeti változók
`EDITORIAL_ALLOWED_EMAIL`: kizárólag engedélyezett Google-fiók
`EDITORIAL_PRIVATE_REPO`: pl. `tulajdonos/privat-editorial-data` (valóban PRIVATE repó)
`EDITORIAL_GITHUB_TOKEN`: csak a privát adattárhoz szükséges contents read/write jogosultságú, minimális jogosultságú token
`OPENAI_API_KEY`: magyar fordításhoz, szerveroldalon
Google OAuth: hozz létre OAuth web clientet a Google Cloud Console-ban; a redirect URI a telepített Streamlit URL + `/oauth2callback`. A Streamlit `st.login('google')` a titkosított `[auth]` és `[auth.google]` beállításokat használja. A Google e-mailt és `email_verified` mezőt ellenőrizzük. A `cookie_secret` hosszú véletlenszerű titok legyen.
Adatok
A privát adattárban az `archive/YYYY-MM-DD.json` a szűrés ELŐTTI napi rekordokat tartalmazza, a `reviews/YYYY-MM-DD.json` pedig a kézi döntéseket. A jelen csomagban a privát adattárat feltöltő GitHub Actions-folyamat még nincs aktiválva, mert a privát repo és az authentikáció beállítása szükséges. Enélkül a felület a hiányzó archívumot jelzi, nem mutat kitalált adatokat. A korábbi napok csak akkor vizsgálhatók teljesen, ha a SQLite-adatbázisból hitelesen visszaexportálhatók.
Következő integráció
Privát GitHub adattár létrehozása és token korlátozása.
Google OAuth kliens és HTTPS Streamlit host konfigurálása.
Szűrés előtti, napi archiválás az Actions workflow-ban (private repo, nem a nyilvános dashboard-data.json).
A kézi döntések validálása és alkalmazása a publikáció előtt, auditnaplóval; Source Intelligence érintetlen.
A forráskód a publikus monitorrepó `manual_editorial_dashboard/` mappájába feltölthető, de valódi tokent és OAuth secretet soha ne tölts oda.
