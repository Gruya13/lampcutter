# Test podaci

Uzorci slika i referentne maske (specifikacija, 13.3).

## Sintetički benchmark uzorci (privremeno)

Dok ne stignu stvarne fotografije, u ovom folderu su **sintetički mockupi** za
benchmark i smoke testove:

| slika | opis | visina |
|---|---|---|
| `srce.png` | glatka kontura srca sa simuliranim sjajem ivice | 200 mm |
| `figura8.png` | dva kruga spojena uskim vratom (test tankih delova) | 220 mm |
| `ploca.png` | zaobljena ploča sa okruglom rupom | 150 mm |

`ref/<ime>.png` su tačne binarne maske (generisane zajedno sa slikama).

> **Nisu zamena za stvarne fotografije.** Za Fazu E treba 2–3 fotografije upaljene
> lampe (ne mockup) + 2–3 mockupa sa poznatim visinama; tada se sintetički uzorci
> mogu zadržati samo za CI smoke test.

## Stvarni uzorci (čekaju se)

5–10 slika, uključujući stvarne fotografije upaljene lampe, sa ručno korigovanim
referentnim maskama u `ref/`.
