# Data quality report

## Out of scope
- **1 match** dropped as not professional tennis (**123** point rows). Not a quality finding: the rows are intact, they record a different level of the sport. The rule is the age bracket, not the word "juniors" — the ITF Junior Circuit's 18-and-under slam events are kept, and this corpus reaches them through Federer, Tsitsipas, De Minaur and Raducanu.
  - `20131001-M-Nike_Junior_Tour-F-Jannik_Sinner-Gabriele_Felline` — Nike Junior Tour

## Ingest repairs
- Match rows with fields shifted out of their columns: **9**
  - dropped — the same match_id also arrived intact, so nothing is lost: **8**
    - `20240915-M-Davis_Cup_World_Group-RR-Botic_Van_De_Zandschulp-Matteo_Berrettini`
    - `20221111-W-BJK_Cup_Finals-RR-Coco_Gauff-Katerina_Siniakova`
    - `20221111-W-BJK_Cup_Finals-RR-Alize_Cornet-Lesley_Pattinama_Kerkhove`
    - `20221110-W-BJK_Cup_Finals-RR-Paula_Badosa-Harriet_Dart`
    - `20221110-W-BJK_Cup_Finals-RR-Magdalena_Frech-Karolina_Muchova`
    - `20221110-W-BJK_Cup_Finals-RR-Elisabetta_Cocciaretto-Bianca_Andreescu`
    - `20221109-W-BJK_Cup_Finals-RR-Yulia_Putintseva-Nuria_Parrizas_Diaz`
    - `20221109-W-BJK_Cup_Finals-RR-Magdalena_Frech-Danielle_Collins`
  - repaired — fields realigned, players read back out of the match_id: **1**
    - `20221110-W-BJK_Cup_Finals-RR-Martina_Trevisan-Leylah_Fernandez`
  - dropped — players unrecoverable: **0**
- Match rows missing `Surface`, displacing everything after it (an umpire lands in the surface column, best-of reads 1): **2** — surface through charted-by nulled, since how far the tail moved is not knowable
    - `20240915-M-Davis_Cup_World_Group-RR-Tallon_Griekspoor-Flavio_Cobolli`
    - `20221111-W-BJK_Cup_Finals-RR-Danielle_Collins-Marketa_Vondrousova`
- Matches charted more than once: **14** — one chart kept per match, **2,475** point rows dropped
  - `19850907-M-US_Open-SF-Ivan_Lendl-Jimmy_Connors` — charts of 210, 104; kept 210  ← charts disagree
  - `19890609-M-Roland_Garros-SF-Michael_Chang-Andrei_Chesnokov` — charts of 301, 301; kept 301
  - `19910907-M-US_Open-SF-Jim_Courier-Jimmy_Connors` — charts of 178, 148; kept 178  ← charts disagree
  - `19920606-M-Roland_Garros-SF-Jim_Courier-Andre_Agassi` — charts of 90, 254; kept 254  ← charts disagree
  - `19920705-M-Wimbledon-F-Andre_Agassi-Goran_Ivanisevic` — charts of 293, 314; kept 314  ← charts disagree
  - `19930704-M-Wimbledon-F-Jim_Courier-Pete_Sampras` — charts of 255, 255; kept 255
  - `19960706-W-Wimbledon-F-Steffi_Graf-Arantxa_Sanchez_Vicario` — charts of 145, 145; kept 145
  - `19990704-M-Wimbledon-F-Pete_Sampras-Andre_Agassi` — charts of 191, 191; kept 191
  - `20010908-W-US_Open-F-Serena_Williams-Venus_Williams` — charts of 115, 115; kept 115
  - `20160718-M-Washington-R64-Dudi_Sela-Taylor_Fritz` — charts of 138, 138; kept 138
  - `20190212-M-Buenos_Aires-R16-Aljaz_Bedene-Diego_Schwartzman` — charts of 161, 161; kept 161
  - `20220112-W-Australian_Open-Q2-Indy_De_Vroome-Dalma_Galfi` — charts of 254, 254; kept 254
  - `20220812-M-Canada_Masters-QF-Hubert_Hurkacz-Nick_Kyrgios` — charts of 204, 204; kept 204
  - `20230227-M-Dubai-R32-Alejandro_Davidovich_Fokina-Malek_Jaziri` — charts of 76, 76; kept 76
- Point rows repeating a point number with identical content: **140** — one copy kept, lossless
- **Excluded from analysis: 2 match(es)** (339 point rows). Two charts interleaved rather than appended and drifted out of step — the same point number carries a different score and winner in each, so the numbering no longer refers to the same points. The match rows stay; only their points are dropped.
  - `19850907-M-US_Open-SF-Ivan_Lendl-Jimmy_Connors` — 166 rows, 9 point(s) in conflict
  - `19920606-M-Roland_Garros-SF-Jim_Courier-Andre_Agassi` — 173 rows, 1 point(s) in conflict

## Matches
- Total: **11,637**
- Invalid surface: **0** (values: none)
- Missing surface: **3**
- Unparseable date: **10**
- Duplicate match_ids: **0**
- Missing match_id: **0**

## Points
- Total: **1,850,038**
- Missing match_id: **0**
- Missing pt_winner: **0**
- Duplicate (match_id, pt): **0**
- Empty first_serve: **0**
