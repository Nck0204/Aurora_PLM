# Stato di avanzamento

Ultimo aggiornamento: **25 agosto 2026**, fine della sessione 6.

Il progetto e' diviso in 13 sessioni di lavoro. Questa tabella dice a che
punto siamo. Va aggiornata **alla fine di ogni sessione**, prima del commit.

Stati possibili: `da fare` · `in corso` · `completata`

---

## Tabella delle sessioni

| # | Sessione | Stato | Che cosa e' stato realizzato |
|---|---|---|---|
| 1 | Fondamenta | **completata** | Struttura del progetto, ambiente virtuale, configurazione da `.env`, collegamento a PostgreSQL, Alembic, avvio del server, registro su file, gestione errori, rotta `/salute`, primi test, file di governo. Dettaglio sotto. |
| 2 | Modello dati R1 | **completata** | Diciannove tabelle come modelli SQLAlchemy, una migrazione Alembic, dati iniziali idempotenti, test del modello, `docs/MODELLO_DATI.md`. Dettaglio sotto. |
| 3 | Accesso e gestione utenti | **completata** | Password con argon2id, accesso con sessione e "ricordami" rotante, blocco dopo cinque tentativi, cambio password obbligatorio al primo accesso, protezione CSRF, gestione utenti riservata al creatore, registro di audit. Dettaglio sotto. |
| 4 | Sistema grafico | **completata** | Foglio di stile unico con tutti i valori in variabili, quindici componenti come macro Jinja2, barra laterale filtrata per ruolo, vetrina `/stile`, pagine di accesso e gestione utenti ristilate, pagine di errore. Dettaglio sotto. |
| 4b | Anagrafiche | **in parte** | Clienti e contatti: fatti nella sessione 5 (elenco, creazione, modifica, disattivazione, riattivazione). Restano da fare la matrice dei permessi modificabile dall'interfaccia e il cambio di ruolo di un utente. La sessione 6 la matrice la **legge** (D-048), quindi funziona; e' la pagina che la corregge a mancare. |
| 5 | Prodotti, versioni e progetti | **completata** | Clienti e contatti, prodotti con la scomposizione del codice configurabile, versioni e derivazioni, grafo del ciclo di vita con superamento automatico, apertura dei progetti, cruscotto iniziale. Dettaglio sotto. |
| 6 | Archivio documenti | **completata** | Deposito per impronta SHA-256 con deduplicazione e scrittura atomica, caricamento con barra di avanzamento reale, versioni con nota obbligatoria, stato del documento e immutabilita' del rilasciato, ritiro logico con ripristino, scarico registrato, filigrana sui PDF delle versioni superate, permessi calcolati sulla matrice. Dettaglio sotto. |
| 7 | Fasi e assegnazioni | da fare | L'apertura del progetto, la squadra e la scelta del modello di fasi sono state fatte nella sessione 5. Restano: passaggi di fase con richiesta e approvazione, modifica della squadra a progetto avviato, chiusura di un progetto. **Le sessioni 6 e 7 sono state invertite rispetto al piano della sessione 2**: l'azienda ha chiesto prima i documenti. |
| 8 | Revisioni e approvazioni | da fare | Il ciclo bozza / in verifica / rilasciato / superato e' stato fatto nella sessione 6. Restano il flusso di **approvazione** con verificatore e approvatore distinti, la presa in carico (R2) e le notifiche a chi deve verificare. |
| 9 | Interfaccia completa | da fare | Struttura di navigazione, ricerca, elenchi con filtri e paginazione, rifinitura del tema scuro. |
| 10 | Notifiche e posta | da fare | Adattatore di posta doppio (locale/Graph), archiviazione dei messaggi, smistamento automatico e quarantena, allegati, modelli dei messaggi, notifiche. |
| 11 | Lavori pianificati e manutenzione | da fare | APScheduler, controlli notturni, procedura di backup e di ripristino. |
| 12 | Rapporti ed esportazioni | da fare | Cruscotto, rapporti di avanzamento, esportazione in CSV e PDF. |
| 13 | Messa in produzione | da fare | Irrobustimento, prestazioni, installazione sul server aziendale, manuale d'uso, consegna. |

> **Nota sul piano.** Il contenuto delle sessioni da 3 a 13 e' stato riscritto
> alla fine della sessione 2, dopo che il modello dati e' stato realizzato tutto
> insieme invece che una tabella per sessione (vedi `docs/DECISIONI.md`, D-021).
> Le sessioni successive non creano piu' tabelle: ci costruiscono sopra il
> comportamento. Resta una **domanda aperta**: le tabelle di distinta base e
> articoli sono del rilascio R3 e in questo piano non compaiono; va chiarito se
> le 13 sessioni coprono il solo R1 o arrivano anche a R2 e R3.

---

## Sessione 6 — Archivio documenti · completata (25 agosto 2026)

La sessione ha costruito **il mestiere di Aurora**: i documenti. Fino a ieri
il programma sapeva descrivere prodotti, versioni e progetti; da oggi ci mette
dentro i file, li versiona, li protegge e li restituisce.

> **Nota sull'ordine delle sessioni.** Il piano scritto alla fine della
> sessione 2 metteva l'archivio documenti alla sessione 7 e le fasi alla 6.
> L'azienda ha chiesto di invertirle: i documenti sono la parte che serve
> prima. La riga 6 della tabella qui sopra e' quindi l'archivio documenti, e
> i passaggi di fase restano da fare. Le due sessioni non si toccavano: le
> fasi vivono sul progetto, i documenti dentro il progetto.

> **Nessuna migrazione.** `documents`, `document_versions`, `classifications`
> e `permission_rules` c'erano tutte dalla sessione 2. Questa sessione ci ha
> costruito sopra soltanto comportamento e pagine, che e' esattamente quello
> che D-021 si aspettava. `alembic current` non si muove.

### Realizzato

**L'archivio fisico** (`app/services/storage.py`) — il file non si salva con
il suo nome. Si calcola l'impronta SHA-256 del contenuto e il file finisce in
`STORAGE_PATH/objects/<primi 2>/<successivi 2>/<impronta intera>`. Il nome
originale, il tipo e tutto il resto stanno nel database.

Tre regole, e sono tutte e tre il motivo per cui il modulo esiste:

| Regola | Come |
|---|---|
| **Deduplicazione** | Se quell'impronta c'e' gia', il file non viene riscritto. Due documenti condividono un oggetto solo. |
| **Scrittura atomica** | Si scrive su `storage/tmp/<casuale>.parziale`, si fa `fsync`, e solo allora `os.replace()` lo sposta al suo posto. Un'interruzione non lascia un file troncato che sembra buono (D-047). |
| **Limite durante la lettura** | `MAX_UPLOAD_MB` (2 GB di partenza) si verifica **mentre** il file arriva, non dopo: un file da 8 GB non riempie il disco prima di essere rifiutato. |

Il temporaneo sta dentro `STORAGE_PATH` e non nella cartella di sistema
perche' `os.replace()` e' atomico solo dentro lo stesso volume, e in
produzione l'archivio sta su un disco dedicato.

**Servizi nuovi** (`app/services/`):

| File | A che cosa serve |
|---|---|
| `storage.py` | L'archivio fisico: deposita, ritrova, verifica. Non sa niente di documenti. |
| `documents.py` | Documenti e versioni: creazione, versione nuova, stato, ritiro, ripristino, scarico, ricerca. |
| `permissions.py` | La matrice (ruolo x classificazione), in due forme che devono dire la stessa cosa (D-048). |
| `watermark.py` | La filigrana diagonale sui PDF delle versioni non piu' valide. |
| `doc_types.py` | L'elenco dei tipi di documento, letto da `config/tipi_documento.toml` (D-050). |

**Il secondo ciclo di vita** — un documento passa per `bozza`, `in verifica`,
`rilasciato`, `superato`. Il grafo sta in `TRANSIZIONI_DOCUMENTO`, **dentro
`lifecycle.py`** accanto a quello delle versioni di prodotto, perche' la
regola di D-042 dice che due stati non si confrontano da nessun'altra parte
(D-044):

```
bozza <--> in verifica --> rilasciato --> superato
  ^                             |
  +---- (si carica una versione nuova) --+
```

**Il rilasciato non si sostituisce, e non perche' qualcosa lo vieti.** Le
righe di `document_versions` non si modificano mai: caricare un file su un
documento rilasciato crea la **versione successiva** e riporta il documento in
`bozza`, che dovra' rifare il giro della verifica. La versione rilasciata
resta con la sua impronta e il suo file intatto. Sostituire un file non e'
un'operazione che Aurora sappia fare, quindi non c'e' nessun controllo che
qualcuno possa dimenticare di scrivere (D-045).

Il passaggio a `rilasciato` ha la sua **pagina di conferma** - non una finestra
modale, per la stessa ragione di D-042 - e viene registrato con autore e data.
L'autore e la data non hanno una colonna: si rileggono dal registro delle
operazioni con `documents.ultimo_rilascio()`, perche' duplicare un fatto in
due posti vuol dire due verita' che possono divergere.

**La filigrana** (D-046) — se il documento appartiene a una versione di
prodotto `superato` o `obsoleto`:

- **PDF**: esce con una filigrana diagonale semitrasparente su **ogni pagina**,
  calcolata sulla misura di quella pagina, con tre righe: la dicitura
  "VERSIONE SUPERATA - non utilizzare per la produzione", lo stato, e data e
  ora dello scarico. Fatta con pypdf, applicata **al volo** su una copia in
  memoria: nell'archivio il file resta identico a com'e' stato caricato, ed e'
  la sua impronta a dimostrarlo.
- **Tutto il resto**: una pagina di avviso prima dello scarico, e l'avvertenza
  dentro il nome del file (`VERSIONE-SUPERATA_telaio.dwg`) - l'unica cosa che
  resta attaccata al file dopo che e' uscito da Aurora.
- **Se pypdf fallisce**, il file esce com'era, con l'avvertenza nel nome, e il
  guasto finisce nel registro: negare un download per un PDF scritto male
  sarebbe il modo peggiore di sbagliare.

**I permessi, finalmente calcolati sulla matrice** (D-048) — chi vede un
documento lo decide la casella di `permission_rules` all'incrocio fra il ruolo
che la persona ha in **quel** progetto e la classificazione del documento.
`permissions.py` e' l'unico posto che legge quella tabella, e offre la stessa
regola in due forme: `permessi()` per un documento solo e
`filtro_visibilita()` come condizione SQL per gli elenchi. Le due strade
devono dare la stessa risposta, e per esserne certi partono dalla stessa
tabella nello stesso file.

**Pagine** (`app/routers/documents.py`, `app/templates/documenti/`):

| Indirizzo | Che cosa fa |
|---|---|
| `GET /documenti` | Elenco con ricerca sul titolo, filtri per tipo e stato, ordinamento e impaginazione. Con `?progetto={id}` diventa l'elenco di un progetto: **una pagina sola per due usi**. |
| `GET/POST /documenti/nuovo?progetto={id}` | Caricamento con trascinamento o scelta, uno o piu' file insieme, barra di avanzamento reale. |
| `GET /documenti/{id}` | La scheda: dati, storico completo delle versioni con nota e scarico di ciascuna, ultimi scarichi registrati. |
| `GET/POST /documenti/{id}/versione` | La versione nuova, con nota di modifica obbligatoria. |
| `GET/POST /documenti/{id}/stato` | La conferma del cambio di stato, e il cambio. |
| `POST /documenti/{id}/ritira` · `/ripristina` | Ritiro logico e ritorno. |
| `GET /documenti/ritirati` | La sezione dedicata dei ritirati. Solo creatore. |
| `GET /documenti/{id}/versioni/{vid}/scarica` | Il file, con o senza filigrana. Registra lo scarico. |
| `GET /documenti/{id}/versioni/{vid}/avviso` | L'avviso prima di scaricare un formato che non si marchia. |

**Un componente grafico nuovo**: `barra_caricamento.html`, la barra di
avanzamento del caricamento, con la sua sezione 25 in `aurora.css`, il suo
esempio in `/stile` e la sua riga in `docs/GUIDA_STILE.md` - i cinque passi
della sezione 10 della guida. Piu' **due icone**, `scarica` e `ripristina`, e
un macro in piu' in `stato.html`, `etichetta_documento`, che riusa apposta le
tinte degli stati omonimi del ciclo di vita.

L'avanzamento e' **reale**: lo script manda il modulo con una
`XMLHttpRequest`, che sa dire quanti byte sono partiti. Senza JavaScript il
modulo si invia da solo e la barra non compare mai, perche' caricare un
documento e' una delle cose che non possono dipendere da uno script (D-036).

**Configurazione** — due parametri nuovi in `.env` e `.env.example`
(`DOCUMENT_TYPES_CONFIG`, `MAX_UPLOAD_MB`) e un file nuovo in git,
`config/tipi_documento.toml`. Una dipendenza nuova in `requirements.txt`:
`pypdf==6.4.0`, che lavora solo in memoria e non parla con nessun servizio
esterno.

**La barra laterale** — "Documenti" si accende. Restano spente Posta
(sessione 10) e Diagnostica (11).

### Verificato

**Test automatici: 237, tutti superati** (erano 180 alla fine della sessione
5). I 57 nuovi stanno quasi tutti in `tests/test_documenti.py`, divisi come e'
divisa la sessione: archivio, versionamento, immutabilita' del rilasciato,
filigrana, ritiro logico, permessi, pagine, configurazione.

| Criterio di accettazione | Come e' stato verificato | Esito |
|---|---|---|
| Lo stesso file su due documenti: un solo oggetto sul disco | `test_lo_stesso_file_caricato_due_volte_occupa_un_solo_oggetto`, e la prova a mano: 5 versioni, 4 impronte | superato |
| La versione precedente resta scaricabile e identica (impronta) | `test_la_versione_precedente_resta_scaricabile_e_identica` | superato |
| Un rilasciato non si sovrascrive: l'interfaccia lo impedisce e propone la versione nuova | `test_l_interfaccia_non_propone_di_sostituire_un_rilasciato`, `test_caricare_una_versione_su_un_rilasciato_lo_riporta_in_bozza` | superato |
| Filigrana su un PDF di una versione superata | `test_il_pdf_di_una_versione_superata_esce_con_la_filigrana`, che rilegge il PDF ricevuto e ci cerca dentro la dicitura | superato |
| Test su deduplicazione, versionamento, immutabilita' del rilasciato e scrittura atomica | 4 famiglie, 25 test | superato |

Tre test verificano **forma** e non comportamento, e servono a proteggere una
regola: `test_il_grafo_dei_documenti_copre_tutti_gli_stati`,
`test_non_esiste_nessuna_rotta_per_cancellare_un_documento` e
`test_la_versione_e_una_riga_che_non_si_modifica`, che diventa rosso se
qualcuno aggiungesse in buona fede una `documents.modifica_versione()`.

**Prova nel browser**, con il server avviato e il database di sviluppo, sul
progetto vero lasciato dalla sessione 5 - la cui versione di prodotto e'
`superato`, quindi il caso della filigrana e' quello di tutti i giorni:

| Passo | Esito |
|---|---|
| Caricamento di uno schema PDF | superato: documento con versione 1, in bozza |
| Caricamento dello **stesso identico file** come documento diverso | superato: due righe in `document_versions`, un solo oggetto sul disco |
| Due file di meccanica scelti insieme | superato: due documenti, ciascuno con il nome del proprio file come titolo |
| Versione 2 con nota di modifica | superato: la versione 1 resta, con la sua impronta invariata |
| Rilascio di un documento (bozza -> verifica -> rilasciato) | superato: la scheda dice "Rilasciato da Prova Sessione5 il 25/08/2026 alle 15:59", letto dal registro |
| Scheda di un documento rilasciato | superato: nessun pulsante che riporti indietro, solo "Porta a «superato»" e l'invito a caricare una versione nuova |
| Tentativo di tornare in bozza scrivendo l'indirizzo | superato: 400 con "Un documento rilasciato non si riporta indietro... si carica una versione nuova" |
| Scarico del PDF | superato: filigrana su tutte e due le pagine (A4 e A3), nome `VERSIONE-SUPERATA_schema-alimentatore.pdf` |
| Scarico del DWG | superato: dirottato sulla pagina di avviso, poi consegnato con l'avvertenza nel nome |
| Barra di avanzamento con un file da 12 MB | superato: `false\|0%\|Caricamento in corso...` -> `100% - 12.0 MB di 12.0 MB` -> "Il server sta salvando i file..." -> "Caricamento completato." |
| Ritiro di un documento | superato: sparisce dall'elenco, compare fra i ritirati con chi e quando |
| Ripristino | superato: torna com'era, stesso stato e stesse versioni |
| Elenco del progetto | superato: tutte e sette le colonne chieste, piu' i due filtri e la ricerca |
| Ogni campo ha la sua etichetta collegata | superato: 4 campi sulla pagina di caricamento, nessuno scoperto |
| Nessuno scorrimento orizzontale a 1280 pixel | superato |
| `/stile` dopo le aggiunte | superato: 23 icone, la barra di caricamento nelle tre varianti, gli stati di un documento |
| Nessun errore nella consolle del browser | superato |
| Nessun temporaneo rimasto in `storage/tmp/` | superato |

### Difetti trovati e corretti durante la sessione

1. **La filigrana usciva dai bordi su un A4 verticale.** La misura del
   carattere si calcolava sulla **diagonale** della pagina, che e' la risposta
   istintiva e sbagliata: la diagonale e' lunga quanto la riga soltanto se la
   riga e' inclinata esattamente come la diagonale. Con un A4 e
   un'inclinazione di 38 gradi, il testo sbordava di una novantina di punti
   per parte.

   Il calcolo giusto e' che una riga lunga L inclinata di un angolo occupa
   `L*cos(angolo)` in orizzontale e `L*sin(angolo)` in verticale, e deve
   starci tutte e due le volte. Il test che lo protegge non guarda il PDF -
   guardare un PDF non e' una cosa che un test sappia fare - ma **misura**:
   prende il corpo che il servizio sceglie e verifica l'ingombro su cinque
   misure di pagina, dalla cartolina all'A0.

2. **Il test della voce di menu spenta e' diventato rosso, e doveva.**
   `test_le_sezioni_non_ancora_fatte_non_sono_collegamenti` guardava
   "Documenti", che da questa sessione e' una sezione vera. Il commento dentro
   il test lo prevedeva ed e' stato spostato su "Posta". Non e' un fastidio:
   e' il modo in cui ci si accorge che una voce e' rimasta spenta per
   dimenticanza invece che per scelta.

3. **Le righe di audit scritte nella stessa richiesta hanno la stessa ora.**
   PostgreSQL da a `now()` lo stesso valore per tutta la transazione, quindi
   un test che cercava "l'ultima riga di stato scritta" ordinando per
   `occurred_at` pescava a caso fra le tre. La medicina e' cercare la riga per
   **contenuto** invece che per posizione. Vale per qualunque test futuro che
   guardi il registro, ed e' scritto li' accanto.

4. **La vetrina disegnava la barra di caricamento a mano, e restava vuota.**
   Il primo tentativo scriveva l'HTML della barra dentro `stile.html` invece
   di passare dal macro, e senza larghezze le tre barre d'esempio erano tre
   righe grigie. E' esattamente quello che la sezione 10 della guida vieta.
   Il macro ha adesso un parametro `percentuale`, che le pagine vere non usano
   mai - li' la barra nasce nascosta e la riempie lo script - e che serve alla
   vetrina per mostrarla ferma.

### Scelte prese durante la sessione

Sette decisioni nuove in `docs/DECISIONI.md`, dalla D-044 alla D-050. Le tre
da rileggere prima di toccare i documenti:

- **D-045**, il rilasciato non si sostituisce, e la regola non e' un divieto:
  e' che l'operazione non esiste;
- **D-046**, la filigrana si applica al volo e, se fallisce, il file esce lo
  stesso;
- **D-048**, i permessi si leggono dalla matrice in un posto solo, e la stessa
  regola vale per il documento singolo e per l'elenco.

### Rimasto in sospeso per le sessioni successive

- **La matrice dei permessi non si modifica dall'interfaccia.** Questa
  sessione la **legge** - ed e' la prima che la usa davvero - ma la pagina che
  la corregge non c'e'. Fino ad allora la matrice e' quella scritta da
  `scripts/seed.py`. Insieme a lei resta il cambio di ruolo di un utente:
  sono in sospeso dalla sessione 3.

- **La presa in carico (check-out) non si fa.** Le colonne
  `checked_out_by_id` e `checked_out_at` esistono in `documents` e nessuna
  rotta le valorizza: e' del rilascio R2, ed e' scritto nella sessione.

- **La ricerca dentro il contenuto dei file non si fa.** La ricerca e' sul
  titolo. Anche questa e' R2.

- **Niente anteprime dei file**, come chiedeva la sessione.

- **I documenti non si modificano nei dati.** Titolo, tipo e classificazione
  si scelgono al caricamento e restano. `can_edit` della matrice, in questa
  sessione, governa il cambio di stato e il ritiro. La pagina di modifica dei
  dati di un documento non e' stata chiesta e non e' stata fatta.

- **Gli scarichi si vedono solo sulla scheda del documento**, gli ultimi
  venti, e solo a chi ha il permesso di modifica. Una pagina che risponda a
  "tutto quello che ha scaricato questa persona" e' materia del registro di
  audit navigabile, sessione 11.

- **`storage/objects/` contiene 214 oggetti lasciati dai test.** I test
  depositano contenuti irripetibili apposta (vedi `contenuto_irripetibile()`
  in `conftest.py`), e il rollback della transazione copre il database, non il
  disco. Non sono riferiti da nessuna riga, occupano qualche kilobyte e non si
  cancellano (regola 5). La pagina di diagnostica della sessione 11 e' il
  posto in cui, un giorno, si potranno elencare.

- **Sul database di sviluppo sono rimasti i documenti della verifica a mano**,
  sul progetto della sessione 5: lo schema dell'alimentatore con due versioni,
  la sua copia rilasciata, il telaio e la staffa. Piu' due documenti di prova
  della barra di avanzamento, **ritirati** - restano visibili solo in
  `/documenti/ritirati`. Non si cancellano e fanno comodo: sono il primo caso
  vero su cui provare le sessioni successive.

---

## Sessione 5 — Prodotti, versioni e progetti · completata (25 agosto 2026)

La sessione ha messo in piedi il cuore del programma: **il prodotto, le sue
versioni, il ciclo di vita di ciascuna e il progetto che ci si apre sopra.**
Da qui in avanti Aurora ha qualcosa da mostrare la mattina: la pagina iniziale
non e' piu' un saluto, e' il cruscotto dei progetti.

Insieme a loro sono state fatte anche le **anagrafiche dei clienti** che erano
rimaste in sospeso dalla sessione 4 (riga 4b della tabella): clienti, contatti
e disattivazione. Restano fuori la matrice dei permessi e il cambio di ruolo,
che non servivano a questa sessione.

> **Nessuna migrazione.** Le tabelle c'erano tutte dalla sessione 2. Questa
> sessione ci ha costruito sopra soltanto comportamento e pagine, che e'
> esattamente quello che D-021 si aspettava. `alembic current` non si muove.

### Realizzato

**La scomposizione del codice prodotto, configurabile** — la regola con cui
`RMS1100-24-110SW` viene letto **non sta nel programma**. Sta in
`config/codice_prodotto.toml`, indicato da `PRODUCT_CODE_CONFIG` nel file
`.env`: dentro ci sono un'espressione regolare con gruppi nominati e il nome in
italiano di ciascun gruppo. L'ipotesi di partenza legge modello (`RMS`),
potenza (`1100`), tensione di ingresso (`24`), tensione di uscita (`110`),
variante (`SW`).

Il motivo e' che l'azienda **non ha ancora confermato la regola**: quando lo
fara' si cambia una riga di quel file e si riavvia il server, senza toccare
una riga di codice (D-038). Nessun template sa quanti elementi ha un codice: i
filtri della ricerca si costruiscono da soli su quello che la regola dichiara.

**Un codice che non corrisponde viene accettato lo stesso**, con `code_parts`
vuoto e un avviso visibile in tre punti (anteprima, scheda del prodotto,
elenco). Non esiste in nessun punto del programma un controllo sulla forma di
un codice, e c'e' un test che serve solo a impedire che qualcuno ne aggiunga
uno in buona fede (D-039).

**Servizi** (`app/services/`):

| File | A che cosa serve |
|---|---|
| `product_codes.py` | Legge il file di configurazione, scompone un codice, restituisce le coppie etichetta/valore da mostrare. Non solleva mai. |
| `customers.py` | Clienti e contatti: elenco, creazione, modifica, disattivazione, riattivazione. |
| `products.py` | Prodotti e versioni: creazione (con la V1), ricerca con filtri e impaginazione, derivazione, riscomposizione dei codici. |
| `lifecycle.py` | **Il grafo delle transizioni**, il superamento automatico, chi puo' cambiare stato. |
| `projects.py` | Apertura di un progetto, squadra, e le interrogazioni del cruscotto gia' filtrate per chi guarda. |

**Il grafo del ciclo di vita** sta in una tabella sola,
`TRANSIZIONI_AMMESSE` in `lifecycle.py`, e si legge in dieci righe:

```
in sviluppo --> rilasciato --> in produzione
                    |                |
                    +--> superato <--+
                             |
      (da ogni stato) --> obsoleto
```

Non si torna mai indietro, `obsoleto` e' l'unico stato terminale. Una
transizione fuori dal grafo produce una frase italiana che dice **quali sono
quelle possibili**, non un errore tecnico. I pulsanti delle pagine si
costruiscono sul grafo: un'operazione impossibile non viene nemmeno proposta.

**Il superamento automatico** — quando una versione passa a `rilasciato`, la
precedente dello stesso prodotto passa da sola a `superato`. Prima di
procedere c'e' una **pagina di conferma** (non una finestra modale: se non si
aprisse, l'operazione partirebbe senza che nessuno abbia letto niente) che
dice quale versione verra' superata, con il suo numero e il suo stato di
adesso. Nel registro l'operazione risulta **come azione di sistema**, con
`user_id` nullo: chi ha premuto il pulsante ha rilasciato la versione nuova,
non ha superato la vecchia (D-042).

**Pagine** (`app/routers/`, `app/templates/`):

| Indirizzo | Che cosa fa |
|---|---|
| `GET /` | **Il cruscotto**: i progetti visibili, con codice, versione, cliente, fase, ciclo di vita e responsabile. Filtri per stato e per fase. |
| `GET /clienti` · `/clienti/nuovo` · `/clienti/{id}` | Anagrafica clienti, con i contatti nella stessa pagina. Solo creatore. |
| `POST /clienti/{id}/disattiva` · `/riattiva` | Fuori servizio e ritorno. Nessuna cancellazione. |
| `POST /clienti/{id}/contatti` · `POST /contatti/{id}/disattiva` · `/riattiva` | Le persone di riferimento presso il cliente. |
| `GET /prodotti` | Elenco con ricerca per codice, cliente **e elementi scomposti**, ordinamento e impaginazione. |
| `GET/POST /prodotti/nuovo` | Creazione, con **anteprima in tempo reale** della scomposizione. Solo creatore. |
| `POST /prodotti/anteprima-codice` | Il pezzo di pagina che alimenta l'anteprima. L'unica rotta HTMX. |
| `GET /prodotti/{id}` · `POST /prodotti/{id}` · `/disattiva` · `/riattiva` | Scheda del prodotto con tutte le versioni in ordine cronologico. |
| `GET /versioni/{id}` | Scheda della versione, con **l'avviso in cima** se ne esiste una piu' recente. |
| `GET/POST /versioni/{id}/deriva` | Versione derivata: si sceglie l'origine e si scrive perche'. |
| `GET /versioni/{id}/stato` | **La conferma** del cambio di stato: dice che cosa succedera'. |
| `POST /versioni/{id}/stato` | Esegue il cambio, applicando grafo e superamento automatico. |
| `GET /progetti` · `GET /progetti/{id}` | Elenco e scheda, con la barra delle fasi. |
| `GET/POST /progetti/nuovo?versione={id}` | Apertura del progetto su una versione. Solo creatore. |

**Nessun componente grafico nuovo.** Tutte le pagine sono composte con i
quindici macro della sessione 4. L'unica aggiunta e' **un'icona**, `clienti`,
dentro il componente esistente `icone.html`, con il suo esempio in `/stile`
come vogliono i cinque passi: senza, la voce "Clienti" avrebbe avuto la stessa
icona di "Utenti", e nella barra stretta - dove si vedono le sole icone -
sarebbero state indistinguibili.

**La barra laterale** — "Prodotti" e "Progetti" si accendono, e si aggiunge
"Clienti" (riservata al creatore). Restano spente Documenti (sessione 7), Posta
(10) e Diagnostica (11).

**Configurazione** — due parametri nuovi in `.env` e `.env.example`:
`PRODUCT_CODE_CONFIG` e `PAGE_SIZE`.

### Verificato

**Test automatici: 180, tutti superati** (erano 90 alla fine della sessione 4).
I 90 nuovi stanno in `tests/test_prodotti.py` (23), `tests/test_versioni.py`
(37), `tests/test_progetti.py` (18) e `tests/test_clienti.py` (12).

| Criterio di accettazione | Come e' stato verificato | Esito |
|---|---|---|
| `RMS1100-24-110SW`: scomposizione corretta | `test_il_codice_di_esempio_si_scompone_come_previsto`, `test_la_scomposizione_finisce_nel_database` | superato |
| I campi scomposti sono ricercabili | `test_i_campi_scomposti_sono_ricercabili`, su un elemento, su due insieme e su un valore inesistente | superato |
| V2 per derivazione, rilasciata, V1 superata da sola | `test_la_v2_rilasciata_supera_la_v1_da_sola` e `test_il_giro_completo_dall_interfaccia` | superato |
| Transizione non ammessa: messaggio chiaro | `test_il_rifiuto_e_una_frase_italiana_che_dice_come_si_fa`, `test_una_transizione_non_ammessa_dall_interfaccia_e_leggibile` | superato |
| Test sulla regola di superamento e sul grafo | 17 test fra grafo, superamento e permessi | superato |
| Un utente non assegnato non vede il progetto | `test_chi_non_e_assegnato_non_vede_il_progetto_nel_cruscotto`, e la stessa cosa dal browser | superato |

Due test verificano cose che non sono comportamento ma **forma**, e servono a
proteggere una regola: `test_il_grafo_copre_tutti_gli_stati` (aggiungendo uno
stato a `LifecycleState` diventa rosso, perche' una riga mancante dal grafo si
comporterebbe come uno stato terminale senza che nessuno lo abbia deciso) e
`test_non_esiste_nessuna_rotta_per_cancellare_un_cliente`.

**Prova nel browser**, con il server avviato e il database di sviluppo. Il giro
e' stato fatto per intero, come lo farebbe una persona:

| Passo | Esito |
|---|---|
| Creazione del cliente "Ferrovie Nord Milano" (FNM) | superato |
| Anteprima in tempo reale scrivendo `RMS1100-24-110SW` | superato: modello RMS, potenza 1100, ingresso 24, uscita 110, variante SW, aggiornata da HTMX senza ricaricare |
| Anteprima con un codice fuori regola | superato: "Codice non riconosciuto", con la spiegazione che verra' accettato lo stesso |
| Creazione del prodotto | superato: scheda con la scomposizione e la versione 1 in sviluppo |
| Ricerca `?modello=RMS&tensione_uscita=110` | superato: le cinque tendine sono generate dalla configurazione, con i soli valori esistenti |
| Apertura del progetto sulla V1 | superato: sei fasi del modello "Standard v1", norme copiate, PM assegnato da solo |
| Rilascio della V1 | superato: la conferma dice "nessuna versione verra' superata, questa e' la prima" |
| Derivazione della V2 con motivazione | superato |
| Conferma del rilascio della V2 | superato: **"la versione 1 - che adesso e' rilasciato - passera' automaticamente a superato"** |
| Dopo la conferma | superato: notifica che non sparisce, e la V1 e' `superato` |
| Scheda della V1 dopo il superamento | superato: avviso in cima "Questa non e' la versione corrente" con il collegamento alla 2; i pulsanti di stato si riducono al solo "obsoleto" |
| Transizione non ammessa costruita a mano | superato: 400 con "Una versione «superato» non puo' passare a «in sviluppo». Da qui si puo' andare soltanto a: obsoleto." |
| Cruscotto con un progetto vero | superato: tutte e sei le colonne chieste, piu' i due filtri |
| Ogni campo ha la sua etichetta collegata | superato: 16 campi su cinque pagine, nessuno scoperto |
| Nessuna risorsa esterna nelle pagine nuove | superato |
| Nessuno scorrimento orizzontale, a 1440 e a 1100 pixel | superato: a 1100 la barra laterale si stringe a 60px |
| Contrasto delle etichette di stato negli elenchi nuovi | superato: 5.84:1 |
| La colonna del codice e' in monospazio | superato |
| `/stile` dopo l'aggiunta dell'icona | superato: 21 icone, nessuna disegnata con il ripiego del punto interrogativo |
| Nessun errore nella consolle del browser | superato |

### Difetti trovati e corretti durante la sessione

1. **`pagina()` ha due nomi occupati, e uno e' "nome".** Il modulo dei clienti
   rimandava indietro il nome scritto come `nome=nome`, che pero' e' anche il
   secondo parametro di `pagina()` (il file del template). L'errore che ne
   usciva - `pagina() got multiple values for argument 'nome'` - non dice
   niente a chi lo legge. E' la stessa trappola dei nomi dei macro Jinja
   trovata nella sessione 4. I due nomi occupati sono `nome` e `stato`; si
   passa `nome_cliente`, `stato_scelto`. La nota sta ora nella docstring di
   `pagina()`, che e' il posto in cui si va a leggere.

2. **Un campo di testo vuoto arrivava come campo mancante.** Un modulo inviato
   con una casella vuota produceva un 422 con il messaggio tecnico di FastAPI
   invece del nostro messaggio in italiano: una casella vuota, per il
   protocollo, e' un campo che non c'e'. Tutti i campi che il programma
   verifica da se' hanno ora un valore di partenza vuoto, cosi' la verifica
   arriva sempre al nostro codice e l'utente legge sempre una frase italiana.

3. **`elenco_utenti()` non sapeva escludere i disattivati.** Serviva al modulo
   della squadra di un progetto: proporre di assegnare un lavoro a chi non puo'
   piu' entrare non ha senso. Aggiunto `solo_attivi`, falso di partenza, che
   lascia l'elenco degli utenti come prima.

4. **La verifica a mano ha fatto diventare rossi quarantasei test in una
   volta** - ed e' il difetto piu' istruttivo dei quattro, perche' e' lo stesso
   della sessione 3 ricomparso su un'altra tabella.

   I test usavano `RMS1100-24-110SW` come codice di comodo per creare prodotti.
   Poi la prova nel browser ha creato **quel** prodotto, per davvero, sul
   database di sviluppo; `products.code` e' unico, e da quel momento ogni test
   che creava un prodotto si e' rotto. Il programma non c'entrava niente: i
   test si erano scelti un dato che il programma vero poteva raggiungere.

   La medicina e' quella che la sessione 3 aveva gia' scritto in
   `tests/conftest.py` per i nomi utente, applicata ai codici prodotto:
   `modello_irripetibile()` produce una sigla di sole lettere casuali dopo
   "PRV", e `codice_irripetibile()` ci costruisce intorno un codice con i
   numeri fissi. Cosi' un test puo' ancora affermare che la potenza vale 1100 e
   la tensione di uscita 110 - il codice se lo e' scritto lui - senza poter
   collidere con niente.

   Il codice `RMS1100-24-110SW` resta nei test **che non toccano il database**:
   quelli che verificano la scomposizione sono esattamente il criterio di
   accettazione dell'azienda, e la frase va letta con il codice vero.

   La regola generale, ora scritta in `conftest.py`: **i test si scelgono i
   propri dati dentro uno spazio di nomi che il programma vero non raggiunge.**
   Vale per i nomi utente (due punti), per i cognomi
   (`cognome_irripetibile()`), per le sigle dei clienti e adesso per i codici
   dei prodotti.

### Scelte prese durante la sessione

Sei decisioni nuove in `docs/DECISIONI.md`, dalla D-038 alla D-043. Le tre da
rileggere prima di toccare i prodotti o i progetti:

- **D-038 e D-039**, la regola di scomposizione sta in un file e **un codice
  non si rifiuta mai**;
- **D-042**, il grafo delle transizioni sta in un posto solo e vale anche per
  le operazioni che fa il programma da solo;
- **D-043**, chi non e' assegnato non vede, e il filtro sta
  nell'interrogazione, non nel template.

### Rimasto in sospeso per le sessioni successive

- **Il passaggio di fase non si fa.** Un progetto entra nella prima fase del
  suo modello e li' resta: richiesta, approvazione e storia dei passaggi sono
  la sessione 6. La tabella `phase_transitions` esiste e la riga dell'ingresso
  nella prima fase viene gia' scritta nel registro di audit.

- **La squadra non si modifica dopo l'apertura.** `projects.assegna()` e
  `projects.revoca()` ci sono e sono verificati dai test, ma la pagina che li
  usa no: si assegna alla nascita del progetto e basta. Va con la sessione 6.

- **Un progetto non si chiude.** `closed_at` c'e' nella tabella e la scheda lo
  mostra, ma non c'e' il pulsante. Sessione 6.

- **La matrice dei permessi e il cambio di ruolo** restano da fare, dalla
  sessione 3. Non servivano qui: i permessi di questa sessione sono due
  domande sole ("sei il creatore?", "sei assegnato?"). Serviranno con i
  documenti, nella sessione 7, che e' il posto in cui la matrice viene
  davvero usata.

- **`riscomponi()` non ha una pagina.** Il giorno in cui l'azienda confermera'
  la regola di scomposizione, i prodotti gia' inseriti vanno riportati alla
  regola nuova. La funzione c'e' ed e' verificata; manca il pulsante che la
  richiama su tutti i prodotti. Va nella pagina di diagnostica, sessione 11.

- **I filtri della ricerca prodotti leggono tutta la colonna `code_parts`.**
  Con qualche migliaio di prodotti non si nota. Se un giorno diventassero
  centomila, `valori_degli_elementi()` e' la funzione da riscrivere con
  un'interrogazione per elemento; il commento e' scritto li' accanto.

- **Sul database di sviluppo sono rimasti i dati della verifica a mano.** Il
  cliente "Ferrovie Nord Milano" (FNM), il prodotto `RMS1100-24-110SW` con le
  sue due versioni e il progetto aperto sulla V1. Non si cancellano (regola 5)
  e fanno comodo: sono il primo caso vero su cui provare le sessioni
  successive. Insieme a loro c'e' l'utente `prova.sessione5`, creatore, con
  password `verifica-sessione-cinque`: **e' una password di sviluppo scritta
  qui apposta perche' non protegge niente di reale.** Sul server aziendale
  quell'utente non deve esistere - va disattivato prima della messa in
  produzione, nella sessione 13.

---

## Sessione 4 — Sistema grafico · completata (25 agosto 2026)

La sessione ha costruito il sistema grafico completo e lo ha applicato alle
pagine che c'erano. **Da qui in avanti le pagine non si disegnano piu': si
compongono** con i componenti di `app/templates/components/`, che si vedono
tutti insieme all'indirizzo `/stile`.

Il riferimento da tenere aperto e' `docs/GUIDA_STILE.md`.

> **Nota sull'ambito.** La sessione 4 nel piano comprendeva anche clienti,
> contatti, classificazioni e matrice dei permessi. Questa sessione ha
> realizzato la sola parte grafica, che era gia' un lavoro intero. Le
> anagrafiche restano da fare: vedi la riga della tabella qui sopra.

### Realizzato

**Il foglio di stile** — `app/static/css/aurora.css`, riscritto da capo: 24
sezioni numerate con l'indice in cima, oltre millecinquecento righe. Tutti i
colori, le spaziature, i raggi e le ombre sono variabili dichiarate in `:root`.
Il blocco provvisorio della sessione 3 non c'e' piu' (D-033).

**Quindici componenti**, ciascuno un file in `app/templates/components/` con in
cima **quando si usa e quando non si usa**:

| File | A che serve |
|---|---|
| `icone.html` | venti icone SVG disegnate a mano, che prendono il colore del testo |
| `pulsanti.html` | pulsante (primario, secondario, pericolo, piatto; normale e piccolo), collegamento travestito da pulsante, modulo POST con un pulsante solo e gettone CSRF gia' dentro |
| `campi.html` | testo, area di testo, menu a tendina, casella di spunta, pallini di scelta, campo del gettone. Etichetta collegata ed errore di validazione compresi |
| `tabella.html` | tabella con intestazione ferma, righe alternate, ordinamento fatto dal server e riga "nessun risultato" |
| `stato.html` | etichette dei cinque stati del ciclo di vita, etichette di servizio, stato di un utente |
| `riquadro.html` | il contenitore, con testata, azioni e piede |
| `dialogo.html` | finestra modale su `<dialog>`, con apri e chiudi |
| `avvisi.html` | avviso in linea (resta) e notifica temporanea (sparisce) |
| `ricerca.html` | barra di ricerca GET con i filtri |
| `impaginazione.html` | le pagine di un elenco lungo, con i puntini oltre le sette |
| `schede.html` | schede senza JavaScript, e schede che sono pagine diverse |
| `avanzamento.html` | le fasi di un progetto in fila |
| `descrizione.html` | elenco etichetta/valore, in tre varianti |
| `area_file.html` | area di trascinamento, con il campo file vero sotto |
| `vuoto.html` | riquadro vuoto con spiegazione e azione suggerita |

**Le due impalcature** — `base.html` (barra laterale a icone piu' testo, barra
superiore con nome utente e uscita, area contenuto, contenitore delle notifiche)
e `base_nudo.html`, per le pagine di chi non e' dentro il programma: accesso ed
errori.

**La barra laterale** — `app/navigation.py`. Sei voci: Prodotti, Progetti,
Documenti, Posta, Utenti, Diagnostica, piu' Stile in fondo fra le voci di
servizio. Filtrate per ruolo; le sezioni non ancora realizzate compaiono spente,
con la scritta che dice in quale sessione arriveranno (D-035).

**Le pagine ristilate** — accesso, cambio password, pagina iniziale, elenco
utenti, creazione utente, password assegnata, pagina di errore (che serve anche
il 404 e l'accesso negato, D-037).

**La vetrina** — `GET /stile`, riservata al creatore, in `app/routers/style.py`.
Sei schede: Fondamenta, Pulsanti, Moduli, Elenchi, Segnali, Struttura. Gli
esempi funzionano davvero: la ricerca filtra, l'ordinamento riordina,
l'impaginazione cambia pagina, la finestra si apre. Non tocca il database:
lavora su cinque righe finte scritte dentro il file, cosi' si apre anche il
giorno in cui il database non risponde - che e' proprio uno dei giorni in cui si
va a guardare una pagina di diagnostica (D-034).

**HTMX 2.0.10** — scaricato in `app/static/vendor/htmx.min.js` e servito da noi.
Lo usa la ricerca della vetrina, che pero' resta un modulo GET normale e
funziona senza (D-036).

**JavaScript** — `app/static/js/aurora.js`: notifiche che spariscono da sole,
finestre di dialogo, trascinamento dei file. Niente di indispensabile.

### Verificato

**Test automatici: 90, tutti superati** (erano 51 alla fine della sessione 3).
I 39 nuovi stanno in `tests/test_interfaccia.py`.

| Criterio di accettazione | Come e' stato verificato | Esito |
|---|---|---|
| `/stile` mostra tutti i componenti | `test_la_vetrina_mostra_tutti_i_componenti`, diciannove componenti cercati uno per uno nella pagina | superato |
| `/stile` non ha colori scritti a mano | `test_nessun_colore_scritto_dentro_i_template` su tutti i template | superato |
| Nessun colore fuori dalle variabili | `test_i_colori_stanno_tutti_nelle_variabili` sul foglio di stile | superato |
| Login e gestione utenti hanno l'aspetto definitivo | rese nel browser e ispezionate | superato |
| Senza JavaScript si entra | `test_la_pagina_di_accesso_non_ha_bisogno_di_javascript`, `test_si_entra_davvero_senza_javascript` | superato |
| Senza JavaScript si crea un utente | `test_si_crea_un_utente_senza_javascript` | superato |
| Ogni campo ha un'etichetta collegata | `test_ogni_campo_ha_la_sua_etichetta_collegata` su quattro pagine | superato |
| Contrasto minimo 4.5:1 | misurato dal browser: il peggiore e' 4.66:1 | superato |
| Il menu e' filtrato per ruolo | tre test sulla barra laterale | superato |
| Nessuna risorsa esterna | `test_nessun_template_punta_a_un_indirizzo_esterno`, `test_htmx_e_nel_repository_e_lo_serviamo_noi` | superato |

**Prova nel browser.** Le pagine sono state rese con dati finti e ispezionate
misurando gli stili calcolati, senza toccare il database di sviluppo:

| Verifica | Esito |
|---|---|
| Impalcatura a 1440px: barra laterale 232px, barra superiore 56px, contenuto da 232 | superato |
| Impalcatura a 1100px: barra laterale a 60px, sole icone, nomi come suggerimento | superato |
| Nessuna pagina scorre in orizzontale, tabella da 1108px compresa | superato: scorre la tabella dentro il suo riquadro, non la pagina |
| Contrasti misurati dal browser su tutte le etichette di stato | superato: da 4.66:1 a 5.88:1 |
| Fuoco della tastiera visibile | superato: due pixel di accento con distacco |
| Schede senza JavaScript | superato: un corpo visibile per gruppo, gruppi annidati indipendenti |
| Intestazione della tabella ferma allo scorrimento | superato |
| Notifica temporanea | superato: compare al caricamento e sparisce dopo cinque secondi |
| Finestra modale | superato: si apre, si chiude con Esc, con la crocetta e con il clic sullo sfondo |
| Conferma prima di disattivare un utente | superato: la domanda compare e rispondendo "no" il modulo non parte |
| HTMX si carica dal nostro server e si avvia | superato: `window.htmx.version` vale 2.0.10 |
| La password assegnata resta in monospazio, grande, selezionabile con un clic | superato |
| Nessun errore nella consolle del browser | superato |

### Difetti trovati e corretti durante la sessione

1. **Il macro `menu` copriva le voci della barra laterale.** I macro importati
   da una pagina finiscono nello stesso spazio delle variabili con cui viene
   disegnato anche `base.html`. Quattro test si aprivano con
   `'Macro' object is not iterable`, un messaggio che non dice niente. Il menu a
   tendina si chiama `tendina`; le variabili si chiamano `voci_menu` e
   `voci_menu_servizio`. La regola sta in `docs/GUIDA_STILE.md` e in D-034.

2. **I campi in monospazio non erano in monospazio.** Il carattere dei campi e'
   dichiarato su un selettore che comprende `input[type="text"]`, e un selettore
   con un attributo pesa piu' di una classe sola: la classe `.campo-controllo--codice`
   perdeva. Se ne e' accorta la misura degli stili calcolati nel browser, non la
   lettura del foglio - e' esattamente il tipo di difetto che a leggere non si
   vede. Risolto ripetendo la classe.

3. **La colonna delle etichette dell'elenco descrittivo era troppo larga.**
   Aveva un minimo di 140 pixel, che dentro un riquadro stretto lasciava ai
   valori meno spazio che alle etichette. Ora prende quello che le serve fino a
   un massimo di 200.

### Scelte prese durante la sessione

Cinque decisioni nuove in `docs/DECISIONI.md`, dalla D-033 alla D-037. Le due da
leggere prima di scrivere una pagina:

- **D-034**, i componenti sono macro e `/stile` e' il contratto: non si
  inventano componenti nuovi senza aggiungerli alla vetrina;
- **D-036**, HTMX e' un miglioramento e mai una condizione: prima di aggiungere
  un attributo `hx-`, rispondere a "che cosa succede se lo script non arriva?".

### Rimasto in sospeso per le sessioni successive

- **Le anagrafiche della sessione 4 non sono state fatte.** Clienti, contatti,
  classificazioni e matrice dei permessi modificabile dall'interfaccia restano
  da realizzare. Le tabelle ci sono gia' dalla sessione 2 (`customers`,
  `contacts`, `classifications`, `permission_rules`): manca il comportamento e
  mancano le pagine. Ora che i componenti esistono, sono pagine da comporre.

- **Il cambio di ruolo dall'interfaccia**, che era gia' in sospeso dalla
  sessione 3, e' ancora li'. Va insieme alla matrice dei permessi.

- **La pagina Diagnostica non esiste.** La voce di menu c'e', spenta. Ci
  andranno lo stato del programma (oggi `/salute`, che risponde in JSON), lo
  spazio libero dell'archivio e gli ultimi errori del registro. Sessione 11.

- **L'ordinamento delle tabelle e' realizzato solo nella vetrina.** Il
  componente costruisce i collegamenti giusti; a leggere i parametri e a
  ordinare l'interrogazione dovra' pensarci ogni rotta che mostra un elenco. La
  prima sara' quella dei prodotti, nella sessione 5.

- **L'impaginazione non e' ancora usata da nessun elenco vero.** Gli utenti sono
  pochi e ci stanno in una pagina. Serve dalla sessione 5 in avanti.

- **`app/static/js/copia.js` non riesce a copiare in un browser senza fuoco.**
  Non e' un difetto nuovo e non e' un difetto di Aurora: gli appunti sono
  accessibili solo dopo un gesto vero dell'utente. Il ripiego scritto nella
  pagina ("selezionala a mano") funziona ed e' quello che si vede.

- **La cartella `app/static/vendor/` contiene un file di terzi.** HTMX 2.0.10,
  51238 byte, impronta SHA-256
  `71ea67185bfa8c98c39d31717c6fce5d852370fcdfd129db4543774d3145c0de`. Quando si
  aggiornera', l'impronta va confrontata e la riga qui sopra aggiornata.

---

## Sessione 3 — Accesso e gestione utenti · completata (24 agosto 2026)

L'interfaccia di questa sessione e' **volutamente grezza**: HTML minimo, quel
tanto di CSS che serve perche' le pagine si leggano. La grafica e' della
sessione 4, e quando arrivera' il blocco in fondo ad `app/static/css/aurora.css`
andra' riscritto per intero.

### Realizzato

**Servizi** (`app/services/`, logica richiamabile anche fuori dalle rotte):

| File | A che cosa serve |
|---|---|
| `passwords.py` | Impronte argon2id, verifica, generazione delle password leggibili, rimozione degli accenti. E' l'unico posto in cui si tratta una password. |
| `parole.txt` | 415 parole italiane, da 4 a 8 lettere, senza accenti: l'elenco da cui si compongono le password assegnate. |
| `auth.py` | Sessioni (creazione, ricerca, revoca), tentativi di accesso e blocco, `esegui_accesso()`, `cambia_password()`. |
| `users.py` | Nome utente proposto, creazione, riassegnazione della password, disattivazione e riattivazione, elenco. |
| `audit.py` | La funzione che scrive nel registro delle operazioni, e i nomi delle azioni come costanti. Era il pezzo che mancava dalla sessione 2. |
| `cookies.py` | I nomi dei tre cookie, i loro attributi di sicurezza, la lista d'attesa (D-027). |
| `csrf.py` | Gettone a doppio invio e sua verifica. |

**Collegamento con FastAPI**:

- `app/dependencies.py` — le tre dipendenze `utente_corrente`,
  `richiedi_login`, `richiedi_creatore`, le due eccezioni di dirottamento e la
  rotazione del "ricordami" (D-022, D-023).
- `app/templating.py` — il motore Jinja2 e la funzione `pagina()`.
- `app/main.py` — dipendenza globale CSRF, middleware che consegna i cookie,
  gestori dei due dirottamenti, registrazione dei tre router.

**Pagine** (`app/routers/`, `app/templates/`):

| Indirizzo | Che cosa fa |
|---|---|
| `GET/POST /entra` | Modulo di accesso con `autocomplete` corretti e casella "Ricordami". |
| `POST /esci` · `POST /esci-ovunque` | Chiude questa sessione, oppure tutte. |
| `GET/POST /cambio-password` | Cambio volontario e cambio obbligatorio del primo accesso. |
| `GET /` | Pagina iniziale: chi sei, che ruolo hai, quante sessioni hai aperte. |
| `GET /utenti` | Elenco con stato, ruolo e sessioni aperte. Solo creatore. |
| `GET/POST /utenti/nuovo` | Creazione, con nome utente proposto e password mostrata una volta sola. |
| `POST /utenti/{id}/reimposta` | Password nuova, `must_change_password`, tutte le sessioni revocate. |
| `POST /utenti/{id}/disattiva` · `/riattiva` | Disattivazione e riattivazione. **Nessuna cancellazione, da nessuna parte.** |

**Configurazione** — cinque parametri nuovi in `.env` e `.env.example`:
`COOKIE_SECURE`, `SESSION_HOURS`, `REMEMBER_ME_DAYS`, `LOGIN_MAX_ATTEMPTS`,
`LOGIN_WINDOW_MINUTES`.

**Procedure** — `scripts/reimposta_password.py`, la via di soccorso per quando
nessuno riesce piu' a entrare come creatore. Riassegna la password di un utente
dalla riga di comando e, se serve, lo riattiva. Chiude il sospeso della
sessione 2. `scripts/seed.py` e' stato fatto passare dal servizio password,
come previsto dalla nota nel suo stesso file.

**Nessuna migrazione.** Le tabelle `users`, `user_sessions`, `login_attempts` e
`audit_logs` erano gia' complete dalla sessione 2 e non e' stato necessario
toccarle: questa sessione ci ha costruito sopra soltanto comportamento, che e'
esattamente quello che D-021 si aspettava.

### Verificato

**Test automatici: 51, tutti superati** (erano 5 alla fine della sessione 2).

| Criterio di accettazione | Test | Esito |
|---|---|---|
| Login corretto | `test_login_riuscito_apre_una_sessione` | superato |
| Login errato, messaggio generico | `test_login_sbagliato_da_un_messaggio_generico`, `..._utente_inesistente_dice_la_stessa_cosa` | superato |
| Blocco dopo 5 tentativi | `test_blocco_dopo_cinque_tentativi_falliti` | superato |
| Cambio password obbligatorio al primo accesso | `test_primo_accesso_obbliga_a_cambiare_la_password` | superato |
| Revoca sessioni al cambio password | `test_il_cambio_password_revoca_le_altre_sessioni` | superato |
| Accesso negato a un non creatore | `test_un_utente_normale_non_apre_la_gestione_utenti`, `..._non_puo_nemmeno_agire` | superato |
| Funzionamento del "ricordami" | `test_ricordami_fa_rientrare_dopo_la_chiusura_del_browser`, `test_il_gettone_ricordami_usato_non_vale_piu` | superato |
| Giro completo: creo, ricevo la password, entro, sono obbligato a cambiarla, poi entro normalmente | `test_giro_completo_dalla_creazione_al_primo_accesso` | superato |

**Prova a mano nel browser**, con il server avviato e il database di sviluppo:

| Passo | Esito |
|---|---|
| `scripts/reimposta_password.py admin` assegna una password nuova | superato |
| Entrata come `admin` con quella password | superato: dirottato al cambio password |
| Cambio password e arrivo alla pagina iniziale | superato |
| Creazione di "Nicolò D'Angelo" dall'interfaccia | superato: nome utente proposto `nicolo.dangelo`, accento e apostrofo tolti |
| Password mostrata una volta sola, con pulsante copia | superato: quattro parole italiane unite da trattini, copia riuscita |
| Entrata con l'utente nuovo | superato: dirottato al cambio password |
| Dopo il cambio, navigazione normale | superato |
| `/utenti` con un utente non creatore | superato: 403 con messaggio in italiano |
| La barra in cima non mostra "Utenti" a chi non e' creatore | superato |
| `document.cookie` letto dal browser | superato: vuoto, i cookie sono HttpOnly |
| `autocomplete` sui campi del modulo di accesso | superato: `username` e `current-password` |
| Registro di audit dopo il giro | superato: `user.login`, `user.logout`, `user.created`, `user.password_changed`, `user.password_reset`, ciascuna con autore e indirizzo IP |
| `user_sessions` dopo il giro | superato: solo impronte, nessun gettone in chiaro |
| Nessun errore nella consolle del browser e in `logs/aurora.log` | superato |

**Una cosa scoperta proprio da questa prova a mano.** L'utente
"Nicolò D'Angelo" creato dall'interfaccia e' rimasto sul database di sviluppo,
e ha fatto diventare rosso un test che si aspettava di ottenere
`nicolo.dangelo` dal generatore dei nomi utente: trovandolo occupato, il
programma proponeva giustamente `nicolo.dangelo2`.

Il difetto era nel test, non nel programma, ma e' un difetto che sarebbe
tornato a ogni verifica a mano delle sessioni future. E' stato tolto alla
radice con due convenzioni, scritte in `tests/conftest.py`:

- i test che **si scelgono** il nome utente usano nomi con **due punti**
  (`prova.mario.rossi`); `proponi_username()` ne produce al massimo uno, quindi
  quello spazio di nomi il programma non lo raggiunge e non ci puo' essere
  collisione;
- i test che verificano il nome utente **proposto dal programma** usano
  `cognome_irripetibile()`, un cognome inventato con un pezzo casuale in coda,
  che nel database non puo' gia' esserci.

L'utente "Nicolò D'Angelo" e' stato lasciato dov'e': fa comodo avere sul
database di sviluppo un profilo non creatore con cui provare gli accessi
negati, e cancellarlo sarebbe comunque contro la regola 5.

### Scelte prese durante la sessione

Undici decisioni nuove in `docs/DECISIONI.md`, dalla D-022 alla D-032. Le
quattro da rileggere prima di scrivere una pagina nuova:

- **D-028**, la protezione CSRF e' una dipendenza globale: ogni modulo POST
  nuovo deve contenere il campo nascosto, altrimenti riceve un 400;
- **D-032**, lo stato dell'utente si rilegge dal database a ogni richiesta: nel
  cookie non c'e' nient'altro che il gettone;
- **D-027**, i cookie si mettono in lista d'attesa e li consegna un middleware:
  chi ne aggiunge uno deve passare da `programma_cookie()`;
- **D-029**, il blocco dei tentativi e' una finestra che scorre, e chi martella
  tiene chiuso il proprio blocco da solo.

### Rimasto in sospeso per le sessioni successive

- **La grafica.** Le pagine sono grezze di proposito. Il blocco in fondo ad
  `app/static/css/aurora.css` e' un provvisorio dichiarato, da riscrivere nella
  sessione 4.

- **Il registro di audit non si puo' ancora leggere dall'interfaccia.** Le
  righe si scrivono, ma per rileggerle bisogna interrogare il database. Una
  pagina di consultazione, con filtri per persona e per oggetto, e' materiale
  della sessione 9 o della 12.

- **Le sessioni scadute non vengono mai ripulite.** Restano in tabella,
  revocate o scadute: non fanno danno e non si cancellano (D-006), ma la
  tabella cresce. Se un giorno desse fastidio, e' un lavoro pianificato da
  sessione 11 - e sara' comunque un archiviare, non un cancellare.

- **Un utente non puo' vedere le proprie sessioni aperte una per una.** La
  pagina iniziale ne dice il numero e c'e' "Esci da tutti i dispositivi", ma
  l'elenco con dispositivo, indirizzo e data - che le colonne `ip` e
  `user_agent` gia' consentirebbero - non c'e'. Da valutare nella sessione 9.

- **Il cambio di ruolo non si fa dall'interfaccia.** La sessione 3 chiedeva
  elenco, creazione, riassegnazione della password, disattivazione e
  riattivazione, e c'e' tutto; il ruolo si sceglie alla creazione e poi non si
  cambia piu'. Il codice e' pronto (D-032: il ruolo si rilegge a ogni
  richiesta), manca solo la pagina. Sessione 4, insieme alla matrice dei
  permessi.

- **`COOKIE_SECURE` va acceso in produzione.** In sviluppo vale `false` per
  forza. Nella sessione 13 va verificato che valga `true` e che davanti ci sia
  davvero https, altrimenti la sessione viaggia in chiaro sulla rete aziendale.

- **La password di sviluppo di `admin`.** Durante la verifica di questa sessione
  e' stata riassegnata e poi cambiata. Non e' scritta qui e non va scritta da
  nessuna parte nel repository: una password in git e' una password che resta
  in git per sempre, anche dopo essere stata cambiata. Chi riprende il lavoro
  e non ce l'ha se ne assegna una nuova in dieci secondi:

  ```powershell
  python scripts/reimposta_password.py admin
  ```

---

## Sessione 2 — Modello dati R1 · completata (24 agosto 2026)

### Realizzato

- **Diciannove tabelle** come modelli SQLAlchemy, un file per tabella in
  `app/models/`, tutte importate in `app/models/__init__.py`:

  | Argomento | Tabelle |
  |---|---|
  | Persone e accessi | `users`, `user_sessions`, `login_attempts` |
  | Anagrafiche | `customers`, `contacts` |
  | Prodotti | `products`, `product_versions` |
  | Progetti | `projects`, `assignments` |
  | Permessi | `classifications`, `permission_rules` |
  | Documenti | `documents`, `document_versions` |
  | Fasi | `phase_templates`, `phases`, `phase_transitions` |
  | Posta | `email_messages`, `email_attachments` |
  | Tracciabilita' | `audit_logs` |

- **`app/models/base.py`** — i pezzi comuni: `UuidPrimaryKeyMixin` (chiave
  primaria UUID generata da Python), `TimestampMixin` (`created_at` e
  `updated_at` con fuso orario), la funzione `pg_enum()` che costruisce i tipi
  enumerati di PostgreSQL con i valori giusti.
- **`app/models/enums.py`** — sei elenchi di stati: `GlobalRole`,
  `SessionKind`, `LifecycleState`, `ProjectRole`, `DocumentState`,
  `EmailAssignmentState`.
- **Migrazione `897359b06e69_modello_dati_r1.py`** — generata con
  `--autogenerate` e corretta a mano in due punti (creazione e cancellazione
  esplicita dei tipi enumerati), entrambi segnalati da un commento nel file.
- **`scripts/seed.py`** — dati iniziali idempotenti: l'utente creatore `admin`
  con password casuale stampata una volta sola, le quattro classificazioni, le
  dodici caselle della matrice dei permessi, il modello di fasi "Standard"
  versione 1 con le sue sei fasi.
- **`tests/conftest.py`** — fixture `db_session` che lavora dentro una
  transazione sempre annullata: i test toccano il database vero senza
  sporcarlo. Se PostgreSQL non risponde o le migrazioni non sono passate, i
  test si saltano invece di fallire.
- **`tests/test_models.py`** — due test: la catena delle derivazioni fra
  versioni di prodotto e il vincolo di unicita' del numero di versione.
- **`docs/MODELLO_DATI.md`** — ogni tabella con la sua riga di spiegazione, il
  dettaglio delle colonne, la mappa dei collegamenti, i tipi enumerati e le
  scelte che vanno confermate.

### Verificato

| Criterio | Esito |
|---|---|
| `alembic upgrade head` crea tutte le tabelle senza errori | superato: 19 tabelle e 6 tipi enumerati |
| `alembic downgrade base` le rimuove senza errori | superato: non resta niente, nemmeno i tipi enumerati |
| Il giro completo si ripete (`upgrade`, `downgrade`, `upgrade`) | superato |
| `alembic check` non trova differenze fra modelli e migrazione | superato |
| `python scripts/seed.py` popola i dati iniziali | superato: 1 utente, 4 classificazioni, 12 regole, 1 modello con 6 fasi |
| Rieseguirlo non duplica niente | superato: al secondo e terzo giro i conteggi non cambiano |
| Test della relazione `derived_from` | superato |
| `pytest` passa | superato: 5 test, nessun avviso |
| `docs/MODELLO_DATI.md` documenta ogni tabella | superato |

### Scelte prese durante la sessione

Otto decisioni nuove in `docs/DECISIONI.md`, dalla D-013 alla D-021. Le tre che
conviene rileggere prima della sessione 3:

- **D-013**, chiavi primarie UUID e codici parlanti come attributi: e' il
  principio che regge tutto il resto del modello;
- **D-019**, i tipi enumerati vanno creati e cancellati a mano nelle
  migrazioni: se lo si dimentica, il `downgrade` sembra funzionare e il
  successivo `upgrade` fallisce;
- **D-021**, il cambio di piano che ha portato tutto il modello dati dentro
  questa sessione.

Tre punti in cui il modello dice qualcosa di piu' di quanto la sessione avesse
specificato sono elencati in `docs/MODELLO_DATI.md`, sezione 6: `products.customer_id`
obbligatorio, `assignments` con `revoked_at` e `revoked_by_id`,
`documents.doc_type` e `documents.classification_id` obbligatori.

### Rimasto in sospeso per la sessione 3

- **La password di `admin` generata durante la verifica e' visibile
  nell'uscita della sessione di lavoro.** L'utente e' segnato
  `must_change_password`, quindi va cambiata al primo accesso; in alternativa
  si azzera il database (`alembic downgrade base`, `upgrade head`,
  `scripts/seed.py`) e se ne genera una nuova.
- **Un modo semplice per non dimenticare il filtro sulle righe disattivate.**
  Il principio di D-006 obbliga ogni interrogazione a escludere le righe con
  `deleted_at` valorizzato, `revoked_at` valorizzato o `is_active` falso.
  Serve una convenzione, da decidere insieme alle prime interrogazioni vere.
- **La funzione che scrive nel registro di audit.** La tabella c'e', chi ci
  scrive dentro no.
- **Una procedura di riassegnazione della password di `admin`**, per il caso in
  cui quella dei dati iniziali vada persa.

---

## Sessione 1 — Fondamenta · completata (24 agosto 2026)

### Realizzato

- **Struttura del progetto** con le cartelle `app/` (con `models/`,
  `routers/`, `services/`, `templates/`, `static/`), `alembic/`, `docs/`,
  `scripts/`, `tests/`, `storage/`, `logs/`.
- **Ambiente virtuale** in `.venv/` e `requirements.txt` con tutte le versioni
  bloccate.
- **`.gitignore`** che esclude ambiente virtuale, cache di Python, `.env`,
  contenuto di `storage/` e registri.
- **`app/config.py`** — configurazione letta dal file `.env` con
  pydantic-settings. Parametri: `DATABASE_URL`, `STORAGE_PATH`, `SECRET_KEY`,
  `APP_NAME`, `LOG_LEVEL`, `MAIL_PROVIDER`, `MAIL_LOCAL_PATH`. I percorsi
  relativi vengono resi assoluti rispetto alla radice del progetto.
- **`.env.example`** commentato in italiano e **`.env`** con i valori di
  sviluppo.
- **`app/db.py`** — engine SQLAlchemy con verifica della connessione prima
  dell'uso, fabbrica delle sessioni, classe `Base` per i modelli, dipendenza
  `get_db()` per FastAPI.
- **Alembic** inizializzato e collegato a `Base.metadata`; l'indirizzo del
  database lo legge da `.env`, non da `alembic.ini`.
- **`app/main.py`** — applicazione FastAPI con:
  - registro su file rotativo in `logs/aurora.log` (5 MB x 11 file), che
    raccoglie anche le righe prodotte da uvicorn;
  - gestore globale delle eccezioni: annota il dettaglio nel registro con un
    codice di riferimento e mostra all'utente una pagina in italiano priva di
    dettagli tecnici (in JSON se la richiesta non viene da un browser);
  - rotta `GET /salute` che verifica la connessione al database e restituisce
    stato, versione e ora.
- **`app/templates/errore.html`** e **`app/static/css/aurora.css`** — l'unica
  pagina HTML prevista in quella sessione, con il tema scuro di base.
  Nessuna risorsa esterna.
- **`scripts/setup_postgres.md`** — procedura di installazione e preparazione
  del database, con verifica finale e tabella dei problemi frequenti.
- **File di governo**: `CLAUDE.md`, `docs/STATO.md`, `docs/DECISIONI.md`.
- **`README.md`** con l'avvio rapido.
- **`tests/test_salute.py`** — tre test.

### Verificato

| Criterio | Esito |
|---|---|
| `uvicorn app.main:app --reload` avvia il server senza errori | superato |
| `/salute` risponde 200 con `stato`, `versione`, `ora` | superato |
| `pytest` passa | superato |
| I tre file di governo esistono e sono compilati | superato |
| Il foglio di stile viene servito dal nostro server | superato |
| La pagina di errore in italiano compare sui 404 | superato |

### Scoperto durante la sessione

1. **Python installato: 3.14.6, non 3.12.** Vedi `docs/DECISIONI.md`, D-008.
2. **PostgreSQL gia' installato, versione 18.6.** Vedi D-009.

### Sospesi della sessione 1, ora chiusi

- Il database `aurora` e l'utente applicativo sono stati preparati: la
  connessione funziona e `/salute` risponde con il database connesso.
- Il piano delle sessioni 2-13 e' stato rivisto alla fine della sessione 2
  (D-021).
