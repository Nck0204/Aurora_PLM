# Quello che resta da fare

Aggiornato alla fine della **sessione 13**, 1 settembre 2026, con il rilascio
**R1 completato**.

Questo file raccoglie in un posto solo quello che finora era sparso nelle
sezioni «rimasto in sospeso» di `docs/STATO.md`, sessione per sessione. Quelle
sezioni restano dove sono - raccontano il *perche'* una cosa non e' stata
fatta - e questo file dice **che cosa resta, in che ordine, e quanto ne e' gia'
predisposto**.

## Come si legge

Ogni voce ha tre righe che contano:

- **Che cosa manca**, detto come lo direbbe chi lo chiede;
- **Che cosa c'e' gia'**: la parte piu' utile. Quasi tutto quello che resta ha
  gia' sotto la sua tabella, la sua colonna o la sua funzione, perche' il
  modello dati e' stato progettato tutto insieme nella sessione 2 (D-021);
- **Quanto costa**, in giornate di lavoro di una persona che conosce il
  programma. Sono stime, e vanno lette come stime.

Il **peso** dice quanto pesa non averlo:

| | |
|---|---|
| **alto** | qualcuno lo chiedera' entro tre mesi, oppure e' una cosa che manca a un sistema in esercizio |
| **medio** | si sentira' la mancanza, ma si lavora lo stesso |
| **basso** | comodita' |

---

## 0. Prima di tutto: le due cose che riguardano R1 gia' rilasciato

Non sono funzioni nuove: sono cose che l'installazione lascia in sospeso e che
vanno chiuse per prime.

### 0.1 Provare un ripristino su una macchina diversa · **peso alto** · mezza giornata

**Che cosa manca.** Il giro completo `pg_dump → pg_restore` su un database
vuoto, eseguito da una persona, su una macchina che non e' il server.

**Che cosa c'e' gia'.** Tutto: `scripts/backup.py` e `scripts/ripristino.py`
funzionano e sono provati, la procedura passo per passo e' in
`docs/BACKUP_E_RIPRISTINO.md` sezione 7, e il ripristino verifica da solo la
coerenza fra database e archivio.

**Perche' resta a una persona.** Creare un database richiede i diritti di
superutente, che l'utente di Aurora giustamente non ha.

> **E' la prova piu' importante di tutte.** Una copia di sicurezza che non e'
> mai stata ripristinata non e' una copia di sicurezza: e' una speranza. Va
> fatta **prima** che il sistema entri in esercizio, e poi una volta all'anno.

### 0.2 Provare il collegamento alla casella aziendale vera · **peso alto** · un'ora, piu' l'attesa

**Che cosa manca.** Il collegamento a Microsoft Graph non e' mai stato provato
su una casella vera, perche' la registrazione applicativa non esiste ancora.

**Che cosa c'e' gia'.** `FonteGraph` completa e provata contro Graph simulato
(limitazione di frequenza, gettone scaduto, permessi mancanti), la pagina di
configurazione con VERIFICA su ogni campo, e `docs/RICHIESTA_IT.md`, che e' il
documento gia' scritto da mandare all'ufficio informatico.

**Che cosa si e' potuto provare.** Il rifiuto: contro il servizio vero di
Microsoft, con un'organizzazione inesistente, Aurora risponde con la frase
giusta in italiano e scrive il codice `AADSTS` nel registro.

---

## 1. Rilascio R2 — quello che l'azienda ha gia' chiesto

In ordine di peso.

### 1.1 Le notifiche · **peso alto** · 3-4 giornate

**Che cosa manca.** La tabella delle notifiche, i modelli dei messaggi e
l'invio. Chi deve verificare un documento non lo sa finche' non apre Aurora.

**Che cosa c'e' gia'.**

- **le due code servono gia'**: le richieste di passaggio di fase e i loro
  esiti sono avvisi in linea sul cruscotto (D-060), e funzionano;
- **il posto in cui la notifica nascera' e' deciso**: `phase_transitions.seen_at`
  e' la colonna che oggi tiene il «l'ho letto», e diventera' una riga della
  tabella nuova con la sua migrazione. D-060 lo dice per esteso;
- **l'invio non e' da inventare**: `app/services/graph_api.py` e' l'unico file
  che parla con Microsoft e sa gia' autenticarsi, rinnovare il gettone,
  trattare la limitazione di frequenza e tradurre ogni guasto in una frase
  italiana. Mandare un messaggio e' una chiamata in piu' dentro quel file;
- **il lavoro pianificato ha il suo modello**: `app/services/mail_scheduler.py`
  mostra come si accende un lavoro a orologio che non solleva mai (D-080).

**Che cosa c'e' da decidere.** Chi riceve che cosa, e ogni quanto. Un
programma che manda una email per ogni cosa che succede e' un programma le cui
email finiscono in una cartella che nessuno apre.

### 1.2 I rapporti e le esportazioni · **peso alto** · 3-4 giornate

**Che cosa manca.** I rapporti di avanzamento dei progetti e le esportazioni
in CSV e PDF. Era la sessione 12 nel piano, e l'azienda ha chiesto invece la
gestibilita'.

**Che cosa c'e' gia'.**

- **l'esportazione in CSV e' gia' scritta una volta**, per il registro delle
  operazioni: separatore punto e virgola e BOM perche' la apre una persona con
  Excel in italiano (D-066), voce di registro scritta **prima** che il file
  cominci a partire, impronte dentro il file;
- **la generazione di PDF c'e'**: `pypdf` e' gia' installata e
  `app/services/watermark.py` la usa per la filigrana;
- **i dati da mettere nei rapporti sono gia' interrogabili**: la barra
  dell'avanzamento, lo storico delle fasi con le durate, e i conteggi della
  diagnostica sono tutte funzioni gia' scritte e provate.

**Che cosa c'e' da decidere.** Quali rapporti. «Un rapporto di avanzamento» e'
una richiesta che va riempita guardando che cosa fa oggi a mano chi lo
chiede.

### 1.3 Il flusso di approvazione dei documenti · **peso medio** · 2-3 giornate

**Che cosa manca.** Verificatore e approvatore **distinti**: oggi chi verifica
e chi approva sono la stessa persona.

**Che cosa c'e' gia'.**

- **il ciclo di vita del documento c'e'** (`bozza → in verifica → rilasciato →
  superato`), con il suo grafo in `lifecycle.py`;
- **la matrice dei permessi e' predisposta per una colonna in piu'**: la
  sessione 7 aveva gia' previsto «approva» come quarta casella, e la pagina
  `/permessi` disegna la griglia su quello che trova in `permission_rules`;
- **il modello delle due decisioni distinte esiste gia'**, applicato alle
  fasi: `phase_transitions` con `requested_by_id` e `decided_by_id` (D-057) e'
  esattamente la forma che serve.

**Che cosa costa davvero.** Una migrazione (la colonna nella matrice), le
rotte del flusso, e la pagina. Il grafo non cambia.

### 1.4 La presa in carico dei documenti (check-out) · **peso medio** · 1-2 giornate

**Che cosa manca.** Chi sta lavorando a un documento se lo prende, e gli altri
lo vedono preso.

**Che cosa c'e' gia'.** **Le colonne esistono dalla sessione 2**:
`documents.checked_out_by_id` e `documents.checked_out_at`. Nessuna rotta le
valorizza: manca il comportamento, non il modello.

### 1.5 La ricerca dentro il contenuto dei file · **peso medio** · 2-3 giornate

**Che cosa manca.** Oggi la ricerca dei documenti e' sul **titolo**. Cercare
una sigla dentro un PDF non si puo'.

**Che cosa c'e' gia'.** L'archivio per impronta, `pypdf` per leggere i PDF, e
PostgreSQL, che sa fare ricerca a testo pieno da solo (`tsvector`) senza
aggiungere nessun servizio esterno - il che conta, perche' la regola 1 di
CLAUDE.md vieta le dipendenze da servizi cloud.

**Che cosa c'e' da decidere.** Quali formati si indicizzano. I PDF si
leggono; i DWG e i file di CAD elettronico no, e sono meta' dell'archivio.

### 1.6 La modifica della squadra a progetto avviato · **peso medio** · mezza giornata

**Che cosa manca.** Le assegnazioni si danno all'apertura del progetto e si
revocano solo dal codice. Manca la pagina.

**Che cosa c'e' gia'.** **Tutto tranne la pagina**: `projects.assegna()` e
`projects.revoca()` esistono, sono verificate dai test, scrivono le loro righe
nel registro, e le assegnazioni si revocano invece di cancellarsi (D-020).

E' la voce con il rapporto migliore fra quello che serve e quello che manca.

### 1.7 Il cambio di ruolo globale di un utente · **peso medio** · mezza giornata

**Che cosa manca.** Il ruolo si sceglie alla creazione e poi non si cambia
piu'. E' in sospeso **dalla sessione 3**, ed e' il sospeso piu' vecchio del
progetto.

**Che cosa c'e' gia'.** La scheda della persona (`/utenti/{id}`), l'azione
`user.updated` gia' catalogata nel registro, e D-032 - il ruolo si rilegge dal
database a ogni richiesta - che garantisce che un cambio abbia effetto
**subito**, senza far riconnettere nessuno.

**Che cosa c'e' da decidere, ed e' l'unica cosa che manca davvero.** Come si
impedisce all'**ultimo** amministratore di togliersi il ruolo da solo. E'
la stessa precauzione che gia' esiste per la disattivazione
(`test_il_creatore_non_puo_disattivare_se_stesso`), applicata al ruolo.

### 1.8 Le milestone dentro le fasi · **peso medio** · 2-3 giornate

**Che cosa manca.** Le cose da fare **dentro** una fase, e il divieto di
avanzare finche' le obbligatorie non sono fatte.

**Che cosa c'e' gia'.** **Il come si innestano e' gia' scritto per esteso in
D-061**, con le due tabelle (`milestones` appesa a `phases`,
`project_milestones` che racconta il progetto) e la ragione per cui il flusso
non cambia: l'unico punto toccato e' `phases.avanza()`, che oggi ha una
condizione e ne avra' due. Il rifiuto e' gia' previsto (`PassaggioNonAmmesso`),
e i componenti grafici prendono gia' elenchi di dizionari.

Richiesta, approvazione, rifiuto, storico e chiusura non cambiano di una riga.

### 1.9 I controlli notturni · **peso basso** · 1 giornata

**Che cosa manca.** La verifica periodica della catena del registro e la
pulizia dei temporanei rimasti.

**Che cosa c'e' gia'.** `scripts/verifica_audit.py` **e' gia' scritto per
essere pianificato**: ha l'opzione `--silenzioso` e i codici di uscita 0/1/2.
`storage.temporanei_rimasti()` esiste e la diagnostica la usa gia'. E
APScheduler c'e' dalla sessione 11, con il modello di
`app/services/mail_scheduler.py`.

E' quasi tutto fatto: manca l'accensione e la decisione su che cosa fare
quando un controllo notturno trova qualcosa.

### 1.10 L'interfaccia: ricerca trasversale e navigazione · **peso basso** · 2 giornate

**Che cosa manca.** Una ricerca sola che cerchi in tutto - prodotti, progetti,
documenti, posta - invece di una ricerca per sezione. Era la sessione 9 nel
piano, e l'azienda ha chiesto invece il registro delle operazioni.

**Che cosa c'e' gia'.** Elenchi con filtri e impaginazione in ogni sezione,
perche' li ha portati una per volta ciascuna sessione che ne aveva bisogno. E
`permissions.filtro_documenti()` / `filtro_progetti()`, che sono le condizioni
SQL da mettere in qualunque interrogazione nuova perche' non mostri righe di
troppo.

**Che cosa c'e' da decidere.** Se serve davvero. Chi usa Aurora sa in che
sezione sta la cosa che cerca; una ricerca unica e' comoda quando le sezioni
sono tante, e qui sono sei.

### 1.11 L'anteprima dei documenti · **peso basso** · 2 giornate

**Che cosa manca.** Vedere un PDF senza scaricarlo.

**Che cosa c'e' gia'.** Lo scarico con i suoi permessi, la filigrana
applicata al volo, e la registrazione di ogni scarico.

**Che cosa c'e' da decidere, e non e' piccolo.** Un'anteprima nel browser vuol
dire un lettore di PDF nella pagina, cioe' una libreria JavaScript di terzi -
che la regola 2 di CLAUDE.md non vieta (sarebbe un file copiato nel
repository, non una CDN) ma che va soppesata: e' l'unica dipendenza grossa che
Aurora avrebbe dalla parte del browser.

### 1.12 La modifica dei dati di un documento · **peso basso** · mezza giornata

**Che cosa manca.** Titolo, tipo e classificazione si scelgono al caricamento
e restano. Non c'e' la pagina che li corregge.

**Che cosa c'e' gia'.** `can_edit` della matrice, che oggi governa il cambio
di stato e il ritiro, e che governerebbe anche questo.

**Attenzione a una cosa.** Cambiare la **classificazione** di un documento
cambia chi lo puo' vedere: e' un'operazione che va registrata con il valore di
prima e quello di dopo, e probabilmente riservata a chi amministra.

### 1.13 L'elenco delle proprie sessioni aperte · **peso basso** · mezza giornata

**Che cosa manca.** La pagina iniziale dice **quante** sessioni si hanno
aperte e offre «Esci da tutti i dispositivi»; l'elenco con dispositivo,
indirizzo e data no.

**Che cosa c'e' gia'.** Le colonne `user_sessions.ip` e `user_sessions.user_agent`
sono gia' riempite a ogni accesso.

---

## 2. Rilascio R3 — quello che e' stato rimandato per scelta

### 2.1 Distinta base e articoli · **peso alto (per R3)** · 8-10 giornate

**Che cosa manca.** Le tabelle degli articoli e delle distinte base. Sono
**esplicitamente fuori dal rilascio R1** (D-021) e non compaiono nel modello
dati di adesso.

**Che cosa c'e' gia'.** Il posto in cui appenderle: una distinta base
appartiene a una **versione di prodotto**, che e' gia' l'oggetto attorno a cui
gira tutto il resto - documenti, progetti, posta.

**Che cosa c'e' da decidere, ed e' molto.** Se gli articoli sono di Aurora o
arrivano dal gestionale dell'azienda; se la distinta e' a un livello o ad
albero; che cosa succede quando un articolo cambia dopo che una distinta lo ha
usato. E' una sessione intera di progettazione prima di scrivere una riga.

### 2.2 Le domande ancora aperte del piano

Sono scritte in `docs/STATO.md` e vale la pena che restino sotto gli occhi:

- **le tredici sessioni coprivano il solo R1?** La risposta di fatto e' si:
  R1 e' completo e R2/R3 non sono cominciati. Va confermato con l'azienda, e
  va deciso se R2 sara' un secondo blocco di sessioni o un lavoro continuo;
- **la regola di scomposizione dei codici prodotto non e' mai stata
  confermata.** Quella in `config/codice_prodotto.toml` e' un'ipotesi dalla
  sessione 5. Il giorno della conferma si cambia una riga di quel file e si
  esegue `products.riscomponi()` su tutti i prodotti - una funzione che
  **esiste gia' ed e' verificata**, e a cui manca solo il pulsante che la
  richiama. E' mezza giornata, ed e' la voce piu' facile di tutto questo
  elenco.

---

## 3. Piccole cose trovate durante la sessione 13

Sono minute e stanno qui per non perderle.

| Che cosa | Dove | Peso |
|---|---|---|
| `products.riscomponi()` non ha un pulsante che la richiami su tutti i prodotti. Il posto naturale e' la pagina di diagnostica | `app/services/products.py` | basso |
| I filtri della ricerca prodotti leggono tutta la colonna `code_parts`. Con qualche migliaio di prodotti non si nota; con centomila si', e il commento su come riscrivere `valori_degli_elementi()` e' gia' li' accanto | `app/services/products.py` | basso |
| Le sessioni scadute restano in tabella per sempre. Non fanno danno e non si cancellano (D-006), ma la tabella cresce: il giorno in cui desse fastidio, la strada e' archiviare, non cancellare | `user_sessions` | basso |
| Il cruscotto non e' impaginato: mostra tutti i progetti aperti visibili. Con 64 progetti risponde in 40 millisecondi; sopra il migliaio andra' impaginato come gli altri elenchi | `app/services/projects.py` | basso |
| La guida in linea copre l'uso, non l'amministrazione. Chi amministra ha `docs/` e la diagnostica; una guida per lui dentro il programma non e' stata chiesta | `docs/guida/` | basso |
| `app/navigation.py` ha ancora il meccanismo delle voci «spente» (`attiva=False`, `nota=`), che dalla sessione 12 non usa piu' nessuna voce. Ha i suoi test e non fa danno: si toglie il giorno in cui si e' certi che non servira' piu' | `app/navigation.py` | basso |

---

## 4. Che cosa **non** va fatto

Vale la pena scriverlo, perche' sono le cose che qualcuno proporra'.

- **Non si aggiunge un modo di cancellare i dati.** Non e' una dimenticanza:
  e' la regola 5 di CLAUDE.md, e ci sono test che diventano rossi se qualcuno
  aggiunge una rotta che cancella.
- **Non si aggiunge una seconda regola di accesso.** Qualunque cosa nuova
  debba avere dei permessi passa da `permissions.puo()`, e ci sono quattro
  test che leggono i sorgenti per verificarlo (D-051).
- **Non si scrive un `if` sul nome di una fase.** Le fasi sono dati: una
  regola che riguarda una fase in particolare diventa una **colonna** di
  `phases` (D-055), e ci sono due test che lo verificano.
- **Non si aggiunge una funzione che corregge il registro delle operazioni.**
  Il database non lo permetterebbe comunque (D-064).
- **Non si introduce npm, un bundler o un framework JavaScript.** Regola 2 di
  CLAUDE.md.
