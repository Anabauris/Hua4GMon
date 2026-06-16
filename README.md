# Hua4GMon — portatīvs LTE monitors Huawei rūteriem

![Platforma](https://img.shields.io/badge/platforma-Windows%2010%2F11-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Licence](https://img.shields.io/badge/licence-MIT-green)

Tkinter rīks Huawei 4G rūteru (E3372, B315, B525, B535, B628, B818 un
saderīgo) monitoringam. Veidots **antenu montieriem** — palīdz reāllaikā
redzēt, kā mainās signāls pagriežot antenu, izvēlēties labāko bāzes staciju
un fiksēt rezultātu klienta atskaitē.

> Šī ir latviskota versija ar Latvijas operatoru atbalstu (LMT, Tele2, Bite).

## Ko prot

- **LTE parametru monitorings:** RSRP, RSSI, RSRQ, SINR, DL/UL ātrumi,
  sesijas trafiks, mikroshēmas temperatūra, sesijas laiks.
- **Tendences indikators** (↑ / → / ↓) — galvenais montāžas rīks:
  parāda, vai signāls uzlabojas pagriežot antenu.
- **"Jumta režīms"** — pilnekrāna lieli skaitļi, redzami no attāluma
  strādājot ar antenu uz jumta.
- **Audio palīgs** — signāla frekvence atkarīga no tuvuma RSRP maksimumam:
  jo augstāks tonis, jo tuvāk labākajai antenas pozīcijai (Windows).
- **Informācija par torni:** operators pēc PLMN, darba LTE-Band ar frekvenci,
  EARFCN, agregācija (CA), eNodeB, lokālais sektors, PCI.
  + ātra pāreja uz CellMapper.
- **SIM/ierīces informācija:** rūtera IMEI, SIM IMSI un ICCID,
  sērijas numurs, modelis, programmaparatūras versija.
- **Band Lock un antenu pārslēgšana** (iekšējā/ārējā/jaukta)
  caur rūtera API.
- **Rūtera pārstartēšana** ar vienu pogu (noderīgi pēc Band Lock).
- **Sesijas eksports CSV** formātā klienta atskaitei.
- **Automātiska pārpieslēgšanās** ja pazūd savienojums ar rūteri.

## Palaišana

### Gatavs .exe (Windows)

1. Lejupielādēt `Hua4GMon.exe` no [Releases].
2. Ielikt jebkurā mapē.
3. Palaist.

**Ja Windows brīdina "Nezināms izdevējs"** — tas ir normāli
neparakstītiem .exe failiem. Sk. sadaļu [Windows SmartScreen](#windows-smartscreen)
zemāk.

[Releases]: https://github.com/Anabauris/Hua4GMon/releases

### No avota koda (jebkura OS ar Tk)

```bash
git clone https://github.com/Anabauris/Hua4GMon
cd Hua4GMon
pip install -r requirements.txt
python main.py
```

### CLI karodziņi

```
python main.py --ip 192.168.1.1 --password admin
python main.py --verbose          # detalizēts žurnāls stderr
python main.py --version
```

Ja norādīts `--password`, programma pieslēdzas automātiski — ērti
izveidot saīsni konkrētam klientam.

## Lietošana

1. Atveriet cilni **⚙️ Savienojums**, ievadiet IP (pēc noklusējuma
   `192.168.8.1`, B315/B525 — `192.168.1.1`) un rūtera paroli
   (no uzlīmes). Nospiediet **🚀 Pieslēgties** vai vienkārši Enter
   paroles laukā.
2. Pārejiet uz **📈 Monitors**. Augšā — vispārējs savienojuma kvalitātes
   vērtējums, zemāk — lieli RSRP/RSSI/SINR/RSRQ skaitļi ar maksimumiem
   un liela tendences bulta. Kustiniet antenu vadoties pēc bultas
   (↑ = labāk). Apakšā — izvēlētā parametra grafiks.
3. Cilne **🗼 Tornis** parāda, pie kuras bāzes stacijas esat pieslēgti:
   operators, band ar frekvenci, EARFCN, eNodeB-ID, kā arī IMEI/IMSI/ICCID.
   Poga "Atvērt CellMapper" norādīs torņa koordinātes.
4. Kad atrasta labākā pozīcija — var fiksēt frekvences izvēli
   **🎛️ Tīkls** caur Band Lock un/vai piespiedu kārtā pārslēgt antenu
   uz ārējo. Tur arī ir rūtera pārstartēšanas poga.
5. Klienta atskaitei — poga **💾 Eksportēt CSV** monitora cilnē.

## Windows SmartScreen

Pirmoreiz palaižot neparakstītu .exe, Windows parāda:

> «Windows Defender neļāva palaist nezināmu lietotni»

Tas **nav vīruss** — tā ir politika visiem neparakstītiem binārajiem
failiem. Parakstīšanas sertifikāts maksā ~$300/gadā un atvērtā koda
projektam pagaidām nav attaisnojams. Lai palaistu:

1. Nospiediet **«Plašāka informācija»** brīdinājuma logā.
2. Nospiediet **«Palaist jebkurā gadījumā»**.

Windows atcerēsies izvēli un vairs nebrīdinās.

Ja fails ir "bloķēts" (Properties → Unblock), var noņemt bloķēšanu
ar vienu PowerShell komandu:

```powershell
Unblock-File .\Hua4GMon.exe
```

**Pārliecināšanās:** Release ierakstos tiek publicēts .exe SHA256 hash.
Var pārbaudīt:

```powershell
Get-FileHash .\Hua4GMon.exe
```

## Pārbaudītie rūteri

| Modelis     | Programmaparatūra | Statuss      |
| :---------- | :---------------- | :----------- |
| E3372h-153  | 21.x              | ✅ strādā    |
| B315s-22    | 21.x              | ✅ strādā    |
| B525s-23a   | 21.x              | ✅ strādā    |
| B535-232    | 11.x (Stick)      | ✅ strādā    |
| B636-336    | 21.x              | ✅ strādā    |

Ja jums ir cits modelis — atveriet Issue, pievienosim sarakstam.

## Atkarības

- Python 3.10+
- [huawei-lte-api](https://github.com/Salamek/huawei-lte-api) — klients
  Huawei rūteru tīmekļa API.

## .exe veidošana no avota koda

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --noupx --name Hua4GMon main.py
```

Gatavais exe `dist/Hua4GMon.exe` — viens fails, portatīvs, var kopēt
jebkur.

GitHub Actions to dara automātiski uz push taga `vX.Y.Z` —
sk. `.github/workflows/build_lv.yml`.

## Licence

MIT — sk. [LICENSE](LICENSE).

## Ieguldījums

Pull-requesti un issue ir laipni gaidīti. Īpaši vērtīgi:
- testēšanas rezultāti uz neierastiem Huawei modeļiem;
- avāriju ekrānuzņēmumi un `--verbose` žurnāli kļūdām;
- PLMN sarakstu atjauninājumi dažādām valstīm.
