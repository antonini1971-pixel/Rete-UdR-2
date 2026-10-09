# Sito della Rete UdR 2

Sito con mappa interattiva e quadri orari della rete, generato dal GTFS. È un unico file HTML autonomo
(la libreria delle mappe Leaflet è inclusa): si apre con un doppio clic o si pubblica così com'è.

## Funzioni

- **Elenco linee per comune** (il comune con più passaggi della linea) con ricerca per linea o fermata e numero di corse nel giorno scelto.
- **Giorno**: si sceglie una data; linee, corse e partenze seguono i calendari.
- **Calendari**: non si usano `calendar.txt` e `calendar_dates.txt` del GTFS (nessuna eccezione), ma quelli impostati
  in `CALENDARI` in testa a `build_data.py`:
  - `udr2_10` *Scolastico feriale*: dal lunedì al venerdì, dal 12/10/2026 all'08/06/2027;
  - `udr2_20` *Scolastico sabato*: il sabato, dal 12/10/2026 all'08/06/2027.
- **Mappa** (sfondi Esri: stradale, topografica, grigio chiaro, satellite): percorsi della linea con frecce del
  senso di marcia, capolinea P/A, varianti di percorso evidenziabili, filtro per zone, schermo intero, stampa.
- **Quadro orario** per calendario e direzione, con fermate principali o tutte; clic su una corsa per vederla
  sulla mappa, clic su una fermata per le sue partenze del giorno.
- **Vicino a me** e **Bus in viaggio** (posizioni stimate dagli orari programmati, non in tempo reale).
- Orari sempre nel formato **hh:mm**: gli orari del GTFS con i secondi (es. 06:54:30) sono troncati al minuto.

Il GTFS non indica le fermate principali (`timepoint` è sempre 1): sono considerate principali i capolinea,
la prima fermata in ogni comune, i nodi serviti da almeno 4 altre linee e una fermata almeno ogni 5 minuti
di viaggio (parametri in testa a `build_data.py`).

## File

- `template.html`: grafica e funzioni del sito, con i segnaposto per i dati.
- `build_data.py`: legge il GTFS e scrive il sito completo in `sito-mappe/index.html` (pubblicato online) e
  `index.html` nella radice del repo.

## Aggiornare con un nuovo GTFS

**Da GitHub**: *Add file → Upload files*, trascina il nuovo zip GTFS e fai *Commit changes* su `main`.
Il workflow *Pubblica sito mappe* rigenera e ripubblica il sito in un paio di minuti (scheda *Actions*).
Il sito usa lo zip più recente presente nella radice del repo.

**Dal computer** (serve solo Python 3):

```bash
python3 sito-mappe/build_data.py [percorso/GTFS.zip]
```
