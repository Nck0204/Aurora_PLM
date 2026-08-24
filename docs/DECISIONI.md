# Registro delle decisioni tecniche

Ogni scelta tecnica non ovvia va annotata qui **nel momento in cui viene
presa**, con la data e soprattutto con la motivazione. Fra otto mesi nessuno
si ricordera' perche' una cosa e' stata fatta cosi': questo file e' l'unica
difesa contro il "chissa' perche' l'avevamo deciso".

Le decisioni non si cancellano. Se una decisione viene superata, si scrive una
nuova voce che la sostituisce e si segna la vecchia come **superata da D-xxx**.

---

## D-001 — Stack tecnologico

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** FastAPI + Uvicorn come server, PostgreSQL come database,
SQLAlchemy 2.x con Alembic per l'accesso ai dati e le migrazioni, template
Jinja2 generati dal server piu' HTMX per l'interattivita', argon2-cffi per le
password, APScheduler per i lavori pianificati, pytest e httpx per i test.

**Motivazione.** E' uno stack Python interamente locale, senza pezzi che
richiedano un servizio esterno. FastAPI da' documentazione automatica delle
rotte e validazione dei dati senza codice aggiuntivo. SQLAlchemy con
migrazioni Alembic e' l'unico modo serio di far evolvere lo schema di un
database che contiene dati veri. PostgreSQL perche' i dati sono il patrimonio
dell'azienda e servono transazioni, vincoli di integrita' e backup affidabili.

**Conseguenza.** Chi mantiene il programma deve conoscere un solo linguaggio.

---

## D-002 — Niente CDN, niente npm

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Nessuna risorsa caricata da un indirizzo esterno: CSS,
JavaScript, font e icone stanno in `app/static/` dentro il repository.
Nessun `package.json`, nessun bundler, nessun framework JavaScript.

**Motivazione.** Tre ragioni, in ordine di importanza:

1. Il server aziendale puo' restare senza internet, per guasto o per scelta:
   con una CDN il programma si presenterebbe senza grafica proprio nel giorno
   sbagliato.
2. Una risorsa caricata da un dominio esterno e' codice di terzi eseguito nel
   browser degli utenti su dati aziendali riservati.
3. Un processo di compilazione del frontend e' una seconda catena di
   strumenti da tenere aggiornata, con una sua cartella di dipendenze che
   invecchia. Non e' giustificata per un gestionale interno.

**Conseguenza.** L'interattivita' si ottiene con HTMX (un file solo, copiato
nel repository) e con JavaScript semplice scritto a mano.

---

## D-003 — Tema scuro

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** L'interfaccia usa un tema scuro come unico tema. I colori sono
dichiarati una volta sola come variabili CSS in `app/static/css/aurora.css`.

**Motivazione.** Il programma viene usato per molte ore consecutive, spesso
accanto a strumenti di progettazione elettronica che sono anch'essi scuri:
alternare fondo bianco e fondo scuro tutto il giorno stanca la vista. Un tema
solo, invece di due, dimezza il lavoro di verifica dei contrasti e non
richiede il pulsante di scelta.

**Conseguenza.** Ogni nuovo colore va aggiunto fra le variabili in cima al
foglio di stile, mai scritto direttamente dentro una regola.

---

## D-004 — Archivio dei file per impronta

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** I file caricati non vengono salvati con il loro nome originale.
Si calcola l'impronta SHA-256 del contenuto e il file viene depositato in
`storage/` in un percorso derivato dall'impronta, ad esempio
`storage/objects/3f/9a/3f9a2c11...`. Il nome originale, l'autore, la data e i
collegamenti restano nel database.

**Motivazione.**

- **Due caricamenti dello stesso file occupano un file solo.** Nella
  documentazione tecnica succede continuamente: lo stesso datasheet allegato a
  quindici progetti diversi.
- **Il contenuto e' verificabile.** Ricalcolando l'impronta si dimostra che un
  documento approvato non e' stato alterato: per una distinta base o uno schema
  approvato non e' un dettaglio.
- **Niente conflitti di nome.** Due `schema.pdf` diversi non si sovrascrivono.
- **Nomi di file innocui sul disco.** Un nome originale scritto da un utente
  puo' contenere caratteri che su Windows creano problemi.

**Conseguenza.** Quando si toglie il collegamento a un documento, il file
sull'archivio **non** si cancella: potrebbe essere riferito da altri. Vedi
anche D-006.

---

## D-005 — Doppio adattatore per la posta

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** L'invio dei messaggi passa da un'unica funzione applicativa
dietro alla quale ci sono due attuazioni, scelte dal parametro
`MAIL_PROVIDER` nel file `.env`:

- `locale` — il messaggio non parte: viene scritto come file `.eml` nella
  cartella `MAIL_LOCAL_PATH`;
- `graph` — il messaggio parte davvero attraverso Microsoft Graph
  (Microsoft 365).

**Motivazione.** In sviluppo e in collaudo si prova la posta decine di volte:
spedire per davvero significa riempire le caselle dei colleghi e rischiare di
mandare a un cliente vero un messaggio di prova. Scrivere i messaggi su disco
permette di aprirli e leggerli esattamente come li ricevera' il destinatario,
senza server SMTP e senza rete. Microsoft Graph anziche' SMTP perche'
l'azienda usa Microsoft 365 e l'invio SMTP autenticato e' in via di
dismissione.

**Conseguenza.** Nessuna parte del programma chiama mai direttamente le
librerie di posta: passa sempre dal servizio in `app/services/`.

---

## D-006 — Nessuna cancellazione fisica, tutto nell'audit trail

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Non si esegue mai `DELETE` su una tabella applicativa. Ogni
tabella di dati aziendali ha una colonna di disattivazione (`deleted_at`) e le
interrogazioni normali escludono le righe disattivate. Ogni operazione
significativa viene registrata in una tabella di audit con chi, che cosa, su
quale oggetto, quando e da quale indirizzo IP.

**Motivazione.** In un archivio di documentazione tecnica la domanda "chi ha
approvato questa revisione e quando" e "chi ha tolto quel componente dalla
distinta" ha risposte che valgono soldi. Una riga cancellata e' una risposta
persa per sempre. Il costo di tenere tutto e' trascurabile: si parla di
decine di migliaia di righe, non di miliardi.

**Conseguenza.** Ogni interrogazione deve ricordarsi di filtrare le righe
disattivate. Va previsto un modo semplice per farlo senza dimenticarsene, da
definire nella sessione 2 insieme alle prime tabelle.

---

## D-007 — La rotta /salute risponde sempre 200

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** `GET /salute` restituisce sempre il codice HTTP 200, anche
quando il database non risponde. Il verdetto sta nel campo `stato` della
risposta: `"ok"` se tutto funziona, `"degradato"` se il server e' vivo ma il
database non e' raggiungibile. Il campo `database.errore` contiene il motivo.

**Motivazione.** Chi apre questa rotta lo fa proprio quando qualcosa non va, e
vuole leggere che cosa non va. Un 503 con corpo vuoto dice solo "e' rotto";
un 200 che dice "il server e' in piedi, ma non riesco a collegarmi al database
perche' l'autenticazione fallisce" dice dove andare a guardare. La distinzione
fra "il programma e' morto" (nessuna risposta) e "il programma e' vivo ma
zoppica" (risposta con `stato: degradato`) resta comunque leggibile.

**Conseguenza.** Un eventuale programma di sorveglianza non deve guardare il
codice HTTP ma il campo `stato`. Sta scritto nella docstring della rotta.

---

## D-008 — Python 3.14 invece di 3.12

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Il progetto gira su Python 3.14.6, l'unica versione presente
sulla macchina di sviluppo.

**Motivazione.** Era previsto Python 3.12, ma sulla macchina risulta
installato solo il 3.14.6. Tutte le dipendenze del progetto hanno wheel native
gia' compilate per 3.14 (verificato: `psycopg-binary`, `pydantic-core`,
`argon2-cffi-bindings`, `watchfiles` si sono installate senza dover compilare
niente). Installare una seconda versione di Python affiancata alla prima
avrebbe aggiunto confusione senza dare niente in cambio.

**Conseguenza.** Sul **server di produzione** va installata la **stessa**
versione di Python della macchina di sviluppo. Va verificato prima della
sessione 13.

---

## D-009 — PostgreSQL 18 invece di 16

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Si usa il PostgreSQL 18.6 gia' installato sulla macchina, senza
affiancargli una versione 16.

**Motivazione.** Era previsto di installare PostgreSQL 16, ma durante la
sessione 1 e' emerso che il servizio `postgresql-x64-18` era gia' installato e
in esecuzione sulla porta 5432. Aurora non usa nessuna funzionalita' esclusiva
di una versione o dell'altra, e due server PostgreSQL sulla stessa macchina
significano due porte, due cartelle di dati e due backup da tenere distinti:
un'occasione di sbagliare, in cambio di niente.

**Conseguenza.** `scripts/setup_postgres.md` conserva la procedura di
installazione completa (serve per il server aziendale) ma indica in cima che
su questa macchina la parte A si salta.

---

## D-010 — L'indirizzo del database si legge solo dal file .env

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** `DATABASE_URL` sta unicamente nel file `.env`. La riga
`sqlalchemy.url` in `alembic.ini` e' stata commentata; `alembic/env.py`
costruisce il collegamento importando `app.config`.

**Motivazione.** Due copie della stessa password sono una copia di troppo:
prima o poi si aggiorna una e non l'altra, e la migrazione va a finire sul
database sbagliato. In piu' `alembic.ini` verrebbe versionato in git, e la
password con lui. C'e' anche un motivo pratico: `alembic.ini` viene letto da
`configparser`, che tratta il segno `%` come carattere speciale, e le password
codificate in percentuale verrebbero interpretate male.

---

## D-011 — Identificatori in inglese, testi in italiano

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Nomi di variabili, funzioni, classi, tabelle, colonne e file in
inglese. Commenti, docstring, messaggi di errore e testi dell'interfaccia in
italiano. Le chiavi dei JSON destinati all'interfaccia sono in italiano
(esempio: `/salute` restituisce `stato`, `versione`, `ora`).

**Motivazione.** Gli identificatori in inglese si mescolano senza attrito con
le librerie, che sono in inglese, ed evitano gli ibridi illeggibili tipo
`get_progetto_by_codice`. I testi in italiano perche' li leggono i colleghi
che useranno il programma. I JSON dell'interfaccia sono testo mostrato, non
codice: seguono la lingua dell'interfaccia.

---

## D-012 — psycopg 3 in versione "binary"

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Si usa `psycopg[binary]==3.3.4` come driver PostgreSQL.

**Motivazione.** La variante `binary` include gia' compilata la libreria
client di PostgreSQL: si installa su Windows senza compilatore C e senza avere
i file di sviluppo di PostgreSQL sulla macchina. Su un server Windows
aziendale, dove installare Visual Studio Build Tools e' una pratica da
autorizzare, e' la differenza fra un'installazione di due minuti e una
mattinata persa. psycopg 3 anziche' 2 perche' e' quello supportato per il
futuro ed e' quello consigliato da SQLAlchemy 2.x.

**Conseguenza.** In un'eventuale installazione su Linux si valutera'
`psycopg[c]`, che e' piu' veloce ma richiede la compilazione.
