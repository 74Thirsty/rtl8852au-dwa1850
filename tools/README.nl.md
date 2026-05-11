# tools/

[English](README.md) | **Nederlands**

Hulpprogramma's die de maintainer gebruikt voor CTF-uitdagingen,
hardware-debugging en beveiligingsonderzoek op **eigen apparatuur**.
Ze zijn **geen** onderdeel van de driver en worden niet geïnstalleerd
door `make install` of DKMS.

---

## Juridische kennisgeving — uitsluitend geautoriseerd testen

De scripts in deze map sonderen netwerkdiensten. Ze draaien tegen
systemen die je **niet** in eigendom hebt, of zonder expliciete
schriftelijke toestemming van de eigenaar, is in vrijwel elke
jurisdictie een strafbaar feit. De maintainer neemt de toepasselijke
wetten serieus:

| Rechtsgebied   | Wet/artikel                                      | Wat het dekt                                                  |
|----------------|--------------------------------------------------|---------------------------------------------------------------|
| Nederland      | **Sr art. 138ab**                                | Computervredebreuk (onbevoegd binnendringen)                  |
| Nederland      | **Sr art. 350a / 350b**                          | Beschadigen van gegevens / verspreiden van kwaadaardige code  |
| Europese Unie  | **Richtlijn 2013/40/EU**                         | Aanvallen tegen informatiesystemen                            |
| Verenigde Staten | **18 USC § 1030** (CFAA)                       | Onbevoegde toegang tot een beschermde computer                |
| Verenigd Koninkrijk | **Computer Misuse Act 1990, ss. 1–3**        | Onbevoegde toegang, wijziging, verstoring                     |
| Duitsland      | **StGB § 202a / 202c**                           | Hacking-vergelijkbaar + "Hacker-Paragraph" over tool-distributie |
| Australië      | **Criminal Code Act 1995, deel 10.7**            | Onbevoegde toegang, wijziging of verstoring                   |

De maintainer aanvaardt **geen enkele aansprakelijkheid** voor misbruik
van deze scripts. Distributie is uitsluitend voor legitiem onderzoek,
educatie en geautoriseerd testen.

---

## Toegestaan gebruik

- Verifiëren van default-credentials-blootstelling op **camera's die
  je in eigendom hebt**.
- **CTF-uitdagingen** waarbij de organisator expliciet
  netwerkprobing van het target heeft geautoriseerd.
- **Pentest-engagements** met getekende scope-brief / rules of
  engagement van de systeemeigenaar.
- Een systeembeheerder demonstreren hoe een aanvaller hun apparaat
  zou benaderen, met diens **schriftelijke toestemming**.

## Niet toegestaan gebruik

- Probing van **enig** apparaat op een netwerk dat je niet in
  eigendom hebt of beheert, zelfs als je er technisch bij kunt.
- "Even proberen" van credentials op een buurt-, hotel-, café- of
  gastnetwerk-camera.
- Probing van een apparaat waarvan de eigenaar geen schriftelijke
  toestemming heeft gegeven, ook al denk je dat ze ermee instemmen.
- Doorgaan met probing na één mislukte poging waardoor de eigenaar
  het zou opmerken / het verkeer in rekening zou krijgen.

Twijfel je of een test geautoriseerd is, dan is hij dat niet.

---

## Inhoud

### `tapo_rtsp_brute.py`

Multi-threaded RTSP Digest brute-force credential-finder voor
TP-Link Tapo-camera's (en elke RTSP-server die Digest-authenticatie
gebruikt). Implementeert de RTSP DESCRIBE
challenge/response-handshake. Gebouwd voor CTF-oefening in de eigen
homelab van de maintainer en om te verifiëren dat default-credentials
zijn vervangen op camera's onder zijn beheer.

```bash
python3 tools/tapo_rtsp_brute.py <camera_ip> [wordlist]
```

Bij start drukt het script de juridische kennisgeving en wacht 5
seconden — Ctrl+C breekt af. Voor unattended runs tegen je eigen
infrastructuur (geautomatiseerde CTF-labs, geplande checks van je
eigen apparatuur) zet je `RTW_TAPO_AUTHORISED=1` in de omgeving om de
prompt over te slaan.

Het script schrijft niets naar disk en stopt zodra een geldig
credential is gevonden. Bron: ~250 regels, alleen standard library,
geen externe afhankelijkheden.
