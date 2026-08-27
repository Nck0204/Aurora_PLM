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

---

## D-013 — Chiave primaria UUID, codici parlanti come attributi

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Ogni tabella ha come chiave primaria una colonna `id` di tipo
UUID, generata da Python e mai mostrata all'utente. I codici che le persone
leggono e scrivono - codice prodotto, codice cliente, nome utente - sono
attributi normali, con un vincolo di unicita' dove serve, e **non compaiono
mai come chiave esterna**.

**Motivazione.** Un codice parlante prima o poi cambia: l'azienda rivede il
modo di comporre i codici, un cliente viene incorporato, una persona cambia
cognome. Se quel codice e' la chiave, cambiarlo significa rincorrere i
collegamenti in venti tabelle e sperare di non dimenticarne uno; se e' un
attributo, si aggiorna una casella di testo e non succede niente.

UUID invece di un numero progressivo per tre ragioni pratiche: l'oggetto ha il
suo identificatore appena viene costruito, quindi si possono collegare fra loro
righe nuove prima ancora di scriverle; un identificatore che compare in un
indirizzo web non lascia indovinare quante righe ci sono in tabella ne'
permette di sfogliarle cambiando un numero; e un'eventuale unione di due
database non produce collisioni.

**Conseguenza.** Gli indirizzi delle pagine conterranno UUID, che sono lunghi e
brutti da leggere. E' un prezzo accettabile: un indirizzo non lo legge nessuno.

---

## D-014 — Gli stati sono tipi enumerati di PostgreSQL, con valori in italiano

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Gli stati (ciclo di vita di una versione, stato di un documento,
ruolo, tipo di sessione, esito dello smistamento della posta) sono classi
`Enum` di Python mappate su veri tipi enumerati di PostgreSQL. Il **nome della
classe** e' in inglese come tutti gli identificatori; il **valore** e' in
italiano: `in_sviluppo`, `bozza`, `ingegnere`, `quarantena`.

**Motivazione.** Il tipo enumerato del database rifiuta un valore sbagliato al
momento in cui qualcuno prova a scriverlo. Con una colonna di testo libero uno
stato scritto male entra e si scopre sei mesi dopo, in un elenco filtrato che
non torna e che nessuno sa spiegare.

I valori sono in italiano perche' non sono identificatori: sono dati, finiscono
scritti nel database e mostrati all'utente, e sono il vocabolario che in azienda
si usa gia' a voce. La regola 4 di CLAUDE.md riguarda i nomi delle cose, non il
loro contenuto - come le chiavi dei JSON dell'interfaccia, che sono in italiano
per lo stesso motivo (D-011).

**Conseguenza.** Aggiungere o togliere un valore richiede una migrazione, non
la sola modifica di `app/models/enums.py`: il tipo vive nel database.

---

## D-015 — Un file per tabella, tabelle al plurale

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Ogni tabella ha il suo file in `app/models/`, con il nome della
tabella al singolare (`product_version.py`). Le classi sono al singolare
(`ProductVersion`), i nomi delle tabelle al plurale (`product_versions`). I
pezzi comuni - chiave primaria, date di servizio, costruzione dei tipi
enumerati - stanno in `app/models/base.py`; gli elenchi di stati in
`app/models/enums.py`.

**Motivazione.** E' la regola gia' scritta in CLAUDE.md, sezione 4. Diciannove
file corti sono piu' facili da attraversare di tre file lunghi: si cerca il
nome della tabella e si apre quel file. Il plurale per le tabelle risolve anche
un problema pratico: `user` e' una parola riservata di PostgreSQL, `users` no.

**Conseguenza.** Ogni modello nuovo va importato in `app/models/__init__.py`,
altrimenti non risulta in `Base.metadata` e Alembic lo ignora in silenzio.

---

## D-016 — I modelli di fasi sono immutabili e versionati

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Un `phase_template` non si modifica mai. Una correzione produce
una riga nuova con lo stesso nome e `version` aumentato di uno; il modello
vecchio resta, disattivato con `is_active`, e i progetti che lo usano
continuano a puntargli. Le fasi appartengono a un modello e a uno solo: due
modelli con una fase chiamata "Concept" hanno due righe distinte.

**Motivazione.** Un progetto aperto due anni fa e' passato per le fasi che
esistevano allora. Se il modello si potesse correggere a posteriori, la storia
di quel progetto racconterebbe fasi mai esistite e le approvazioni registrate
in `phase_transitions` risulterebbero riferite a passaggi mai avvenuti. In un
archivio di documentazione tecnica una storia che si riscrive da sola non e' un
archivio.

**Conseguenza.** Le fasi si duplicano fra le versioni del modello. E' voluto e
costa niente: si parla di poche righe.

---

## D-017 — La posta si attacca alla versione di prodotto, non al progetto

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** `email_messages` ha una chiave esterna verso `product_versions`,
non verso `projects`.

**Motivazione.** Un progetto si chiude, la corrispondenza con il cliente no:
continua quando il prodotto e' gia' in produzione, e sono spesso proprio quei
messaggi a contenere le richieste di modifica e le deroghe. Attaccare i
messaggi al progetto avrebbe voluto dire non sapere piu' dove metterli il
giorno della chiusura.

**Conseguenza.** Per risalire dal messaggio al progetto si passa dalla versione
di prodotto. E' un salto in piu' in lettura, ed e' quello giusto.

---

## D-018 — `audit_logs.entity_id` non ha chiave esterna

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Nel registro delle operazioni, `entity_id` e' un UUID senza
vincolo di chiave esterna, accompagnato da `entity_type` che dice a quale
tabella si riferisce. Anche `user_id` puo' essere nullo.

**Motivazione.** Una chiave esterna punta a una tabella sola, e questa colonna
deve poter puntare a tutte. In piu' una chiave esterna impedirebbe di
registrare un'operazione su una riga che al momento della scrittura non esiste
ancora - o che non esiste piu' - e la traccia di quelle e' proprio quella che
serve. `user_id` nullo perche' alcune operazioni le fa il programma da solo, in
un lavoro pianificato di notte: meglio nessuna persona che una persona finta.

**Conseguenza.** L'integrita' di questa colonna non la garantisce il database:
la deve garantire il codice che scrive nel registro, e sara' uno solo.

---

## D-019 — Nelle migrazioni i tipi enumerati si creano e si cancellano a mano

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Nella migrazione, i tipi enumerati vengono creati esplicitamente
in cima a `upgrade()` e cancellati esplicitamente in fondo a `downgrade()`. Le
colonne li dichiarano con `create_type=False`. La migrazione
`897359b06e69_modello_dati_r1.py` porta il modello e due commenti che segnalano
i punti corretti a mano.

**Motivazione.** Due difetti dell'autogenerazione, entrambi silenziosi finche'
non fanno danno. Il primo: `project_role` e' usato da due tabelle e Alembic
genera il tipo dentro tutte e due le `create_table`, cosi' la seconda fallisce
perche' il tipo esiste gia'. Il secondo: `DROP TABLE` non cancella i tipi
enumerati, che restano nel database dopo un `downgrade` e fanno fallire il
successivo `upgrade` con "il tipo esiste gia'".

**Conseguenza.** Ogni migrazione che introduce o toglie un tipo enumerato va
riletta e corretta a mano dopo l'autogenerazione. Va verificata provando il
giro completo: `upgrade head`, `downgrade base`, di nuovo `upgrade head`.

---

## D-020 — Le assegnazioni si revocano, non si cancellano

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** `assignments` ha `revoked_at` e `revoked_by_id`, che l'elenco
delle colonne della sessione 2 non prevedeva. L'unicita' di "una persona, un
ruolo per progetto" e' imposta da un indice unico **parziale**, limitato alle
righe non revocate.

**Motivazione.** Senza quelle due colonne un'assegnazione non si potrebbe
togliere in nessun modo compatibile con D-006 (niente cancellazione fisica), e
"chi aveva accesso a quel progetto a marzo" e' una domanda a cui bisogna poter
rispondere. L'indice parziale invece di un vincolo di unicita' normale perche'
altrimenti una persona non potrebbe mai essere riassegnata a un progetto da cui
era stata tolta.

**Conseguenza.** Ogni interrogazione sulle assegnazioni deve filtrare
`revoked_at IS NULL`. E' lo stesso problema gia' aperto da D-006.

---

## D-021 — La sessione 2 realizza tutto il modello dati, non solo gli utenti

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Il piano abbozzato alla fine della sessione 1 assegnava alla
sessione 2 "utenti, accesso e audit trail" e distribuiva le altre tabelle sulle
sessioni 3, 4, 5, 6 e 7. La sessione 2 ha invece realizzato **tutto** il modello
dati del rilascio R1: diciannove tabelle, una sola migrazione, nessuna
interfaccia e nessuna logica applicativa. Le tabelle di distinta base e articoli
restano fuori, sono di R3.

**Motivazione.** Uno schema di database si progetta tutto insieme o non si
progetta. Aggiungere le tabelle una sessione per volta avrebbe prodotto una
catena di migrazioni che si correggono a vicenda - una chiave esterna aggiunta
qui, una colonna resa obbligatoria la', un vincolo che si scopre solo quando
arriva la tabella dopo - e nessuna occasione di vedere l'insieme prima di
scriverlo. Il costo di questa scelta e' una sessione densa; il ricavo e' che le
sessioni successive trovano il terreno gia' pronto e possono occuparsi solo di
comportamento.

**Conseguenza.** Il piano delle sessioni da 3 a 13 in `docs/STATO.md` va
riscritto di conseguenza: quelle sessioni non creano piu' tabelle, ci
costruiscono sopra.

---

## D-022 — Le tre dipendenze dell'accesso hanno il nome in italiano

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Le tre dipendenze di FastAPI che proteggono le rotte si chiamano
`utente_corrente`, `richiedi_login` e `richiedi_creatore`. Sono un'eccezione
dichiarata alla regola 4 di CLAUDE.md, che vuole gli identificatori in inglese.

**Motivazione.** I nomi sono stati indicati espressamente nella specifica della
sessione 3. Sono anche i tre nomi che compaiono nella firma di **ogni** rotta
protetta del programma, quindi sono la cosa che si legge piu' spesso: cambiarli
in inglese avrebbe voluto dire tenere in testa due vocabolari, uno per la
specifica e uno per il codice, per tutte le sessioni a venire.

L'eccezione si ferma qui. Tutto il resto - `esegui_accesso`, `crea_sessione`,
`revoca_sessioni_utente`, `hash_password` - resta in inglese, e la regola 4 vale
ancora per intero per il codice nuovo.

**Conseguenza.** Chi legge `app/dependencies.py` trova tre nomi italiani in
mezzo a codice inglese. E' voluto, ed e' scritto anche li'.

---

## D-023 — Due moduli nuovi fuori dalle cartelle previste

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Nascono due file direttamente sotto `app/`, che la struttura
descritta in CLAUDE.md non prevedeva:

- **`app/dependencies.py`** — le tre dipendenze di FastAPI e le due eccezioni
  di dirottamento;
- **`app/templating.py`** — l'oggetto `Jinja2Templates` e la funzione
  `pagina()` che compone una risposta HTML.

**Motivazione.** Nessuno dei due sta bene dove sarebbe finito altrimenti.

Le dipendenze non sono un servizio: `app/services/` deve restare richiamabile
da uno script o da un lavoro pianificato, e queste funzioni parlano di
`Request`, di cookie e di eccezioni HTTP. Non sono nemmeno un router: non
rispondono a nessun indirizzo. La logica vera sta comunque in
`app/services/auth.py`; qui c'e' solo il collegamento fra quella e FastAPI.

Il motore dei template sta in un modulo proprio per un motivo piu' concreto:
`app/main.py` importa i router, e i router hanno bisogno dei template. Se
l'oggetto restasse in `main.py`, ogni router dovrebbe importare `main` e `main`
importerebbe i router - due moduli che si importano a vicenda, che in Python
funziona solo per caso e smette di funzionare appena si sposta una riga.

**Conseguenza.** La sezione 4 di CLAUDE.md e' stata aggiornata con i due file.

---

## D-024 — I cookie: HttpOnly, SameSite=Lax, Secure da configurazione

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** I tre cookie di Aurora (`aurora_sessione`, `aurora_ricordami`,
`aurora_csrf`) hanno tutti gli stessi attributi: `HttpOnly`, `SameSite=Lax`,
`Path=/` e `Secure` deciso dal parametro `COOKIE_SECURE` del file `.env`, che
vale `false` in sviluppo e **deve** valere `true` in produzione.

**Motivazione.** `HttpOnly` toglie i cookie di mano al JavaScript della pagina:
se un giorno finisse dentro un template uno script ostile, non potrebbe
portarsi via la sessione di chi sta guardando. `SameSite=Lax` fa si' che il
browser non li alleghi alle richieste che partono da un altro sito, ed e' la
prima difesa contro la falsificazione delle richieste.

`Secure` e' un parametro e non una costante per una ragione pratica: dice al
browser di rimandare il cookie **solo** su connessione cifrata. In sviluppo si
lavora su `http://localhost`, e con `Secure` acceso il cookie non tornerebbe
mai indietro: non si riuscirebbe a entrare, e la causa non e' facile da
indovinare. In produzione, dove Aurora sta dietro a https, deve essere acceso,
altrimenti la sessione viaggia in chiaro sulla rete aziendale.

**Conseguenza.** Nella messa in produzione (sessione 13) va verificato che
`COOKIE_SECURE=true` e che ci sia davvero https davanti. Se un giorno Aurora
girasse in rete locale su http senza certificato, questo resta un punto
debole noto e va scritto nella consegna.

---

## D-025 — Del gettone di sessione si conserva l'impronta, e basta un SHA-256

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Al browser va un gettone casuale da 32 byte; nel database, in
`user_sessions.token_hash`, va il suo SHA-256 in esadecimale. Le password,
invece, restano su argon2id.

**Motivazione.** La prima meta' della decisione e' la stessa delle password:
chi si procurasse una copia del database non deve trovarci dentro niente che
permetta di entrare fingendosi qualcun altro.

La seconda meta' - perche' qui basta un SHA-256, che per le password sarebbe
sbagliato - dipende da che cosa si sta difendendo. Una password e' corta e
scelta da una persona, quindi si puo' provare a indovinarla, ed e' per questo
che serve una funzione volutamente lenta e affamata di memoria. Un gettone e'
32 byte estratti a caso dal generatore crittografico: non lo si indovina in
nessun tempo utile, nemmeno provandone miliardi al secondo. Usare argon2 qui
non aggiungerebbe niente e rallenterebbe **ogni singola pagina** di Aurora, che
il gettone lo deve verificare a ogni richiesta.

**Conseguenza.** La lunghezza della colonna, 64 caratteri, e' esattamente
quella di uno SHA-256 scritto in esadecimale: cambiare funzione di impronta
richiederebbe una migrazione.

---

## D-026 — Il gettone "ricordami" ruota a ogni utilizzo

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Ogni volta che il cookie `aurora_ricordami` viene usato per
riaprire una sessione, la riga corrispondente viene revocata e ne viene emessa
una nuova, con la durata piena di trenta giorni che riparte da capo.

**Motivazione.** Un gettone che vale trenta giorni e non cambia mai e' un
gettone che, se qualcuno riesce a copiarlo, vale trenta giorni anche per lui,
in silenzio. Ruotandolo, la copia rubata smette di funzionare la prima volta
che il legittimo proprietario rientra. E se e' il ladro a usarla per primo, e'
il proprietario a ritrovarsi fuori: spiacevole, ma e' anche l'unico modo in cui
qualcuno si accorge che e' successo qualcosa.

La durata che riparte da capo a ogni uso ("scorrevole") serve a non far scadere
il ricordami in faccia a chi usa Aurora tutte le settimane.

**Conseguenza.** Aprire Aurora in due schede nello stesso istante, con la sola
sessione lunga e senza quella corta, puo' far ruotare il gettone due volte e
buttare fuori la seconda scheda. E' una condizione rara - serve che le due
richieste partano prima che la prima abbia risposto - e il rimedio e' rientrare.
Se dovesse capitare spesso, la strada e' un breve periodo di tolleranza sul
gettone appena revocato.

---

## D-027 — I cookie si mettono in lista d'attesa, li consegna un middleware

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Nessuna parte del programma scrive i cookie direttamente nella
risposta. Le funzioni `programma_cookie()` e `programma_rimozione_cookie()` di
`app/services/cookies.py` li mettono in una lista dentro `request.state`, e un
middleware registrato in `app/main.py` li applica alla risposta, qualunque essa
sia, quando ormai e' pronta.

**Motivazione.** Il rinnovo del gettone "ricordami" avviene dentro la dipendenza
`utente_corrente`, cioe' **prima** che la rotta venga eseguita. Se la rotta poi
si ferma con un errore - un 403 perche' la pagina e' riservata al creatore, per
esempio - la risposta che parte e' quella prodotta dal gestore degli errori, che
dei cookie impostati dalla dipendenza non sa niente: andrebbero persi. Il
gettone vecchio pero' e' gia' stato revocato, e l'utente si ritroverebbe fuori
per aver sbagliato pagina.

Con la lista d'attesa i cookie finiscono su qualunque risposta esca: pagina
normale, rimando o pagina di errore.

**Conseguenza.** Chi aggiunge un cookie non deve avere in mano la risposta, il
che e' comodo, ma deve ricordarsi di passare da quelle due funzioni. Il test
`test_il_gettone_ricordami_usato_non_vale_piu` e la coppia di test sugli
attributi dei cookie sorvegliano il meccanismo.

---

## D-028 — Protezione CSRF a doppio invio, applicata come dipendenza globale

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Ogni modulo POST porta un campo nascosto `csrf` il cui valore
deve coincidere con quello del cookie `aurora_csrf`. Il controllo e' dichiarato
**una volta sola**, come dipendenza globale nella creazione dell'applicazione
in `app/main.py`, e vale per tutte le rotte, comprese quelle che verranno.

**Motivazione.** Sul metodo: il gettone viaggia in due posti e devono
coincidere. Chi scrive una pagina ostile puo' far allegare il cookie dal
browser della vittima, ma non puo' **leggerlo** per copiarlo nel campo nascosto,
perche' e' HttpOnly e appartiene a un altro sito. Non serve nessuno stato dalla
parte del server, che per un programma senza memoria condivisa fra i processi
e' esattamente quello che si vuole.

Sul fatto che sia globale: e' l'unico punto di Aurora in cui si e' preferita una
cosa automatica a una esplicita, contro l'abitudine della regola 7. La ragione e'
che qui la dimenticanza **non si vede**. Una rotta a cui manchi il controllo
funziona benissimo, le pagine si aprono, i moduli si inviano, e quello che manca
si scopre il giorno in cui qualcuno ne approfitta. Una protezione che si puo'
dimenticare rotta per rotta, prima o poi si dimentica.

**Conseguenza.** Ogni `<form method="post">` nuovo deve contenere la riga con il
campo nascosto, altrimenti riceve un 400 con la spiegazione in italiano. La
regola e' ricordata in cima ad `app/templates/base.html`, dove la si vede
aprendo qualunque template.

---

## D-029 — Il blocco dei tentativi e' una finestra che scorre sul nome utente

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Un nome utente e' bloccato quando negli ultimi
`LOGIN_WINDOW_MINUTES` minuti risultano almeno `LOGIN_MAX_ATTEMPTS` tentativi
falliti (di partenza: 5 in 15 minuti). Il conteggio si fa sul **nome scritto**,
non sull'utente trovato, e vengono registrati tutti i tentativi, compresi quelli
che il blocco stesso rifiuta.

**Motivazione.** Contare sul nome scritto, e non sull'utente, serve a due cose:
il blocco funziona anche per i nomi utente che non esistono - meta' dei tentativi
interessanti riguarda quelli - e chi prova a indovinare un nome non capisce dal
comportamento del programma se ha azzeccato quello giusto.

La finestra che scorre, invece di un blocco a tempo scritto da qualche parte, si
scioglie da sola man mano che i tentativi vecchi invecchiano: non serve nessuna
colonna in piu' e nessun lavoro pianificato che passi a sbloccare.

**Conseguenza da conoscere.** Siccome anche i tentativi rifiutati dal blocco
contano come falliti, chi continua a martellare tiene chiuso il blocco da solo,
a tempo indeterminato. E' voluto: l'insistenza non deve pagare. Il rovescio e'
che qualcuno puo' tenere chiuso fuori un collega martellando il suo nome utente.
Su una rete aziendale, dove chi puo' farlo e' identificabile e le sue prove
finiscono in `login_attempts` con l'indirizzo IP, e' un rischio accettabile; la
via d'uscita per chi resta fuori e' farsi riassegnare la password dal creatore,
che azzera la questione.

---

## D-030 — Le password assegnate sono quattro parole italiane

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Le password generate dal programma - quella dei dati iniziali,
quella di un utente appena creato, quella riassegnata - sono quattro parole
italiane unite da trattini, estratte senza ripetizione dall'elenco di
`app/services/parole.txt`, che ne contiene 415. Valgono circa 34 bit.

**Motivazione.** Queste password hanno un mestiere solo: essere lette da uno
schermo, magari dettate al telefono, e ribattute a mano **una volta**, perche'
chi le riceve e' obbligato a cambiarle al primo accesso. Una sequenza di
caratteri casuali fa quel mestiere male: si sbaglia a leggerla, non si detta, e
chi la riceve se la scrive su un foglietto - che e' il vero pericolo, molto piu'
dei bit mancanti.

Trentaquattro bit sarebbero pochi per una password permanente. Non lo sono qui:
la password vale un accesso solo, e per provarla a tentativi bisognerebbe
passare dal blocco dopo cinque tentativi falliti, che rende impraticabile
qualunque tentativo in massa.

Le parole rispettano tre regole scritte in cima al file: da 4 a 8 lettere, solo
lettere non accentate, niente parole che si confondano fra loro. Sono tutte
concrete e comuni, perche' devono reggere la lettura ad alta voce.

**Conseguenza.** L'elenco sta nel repository ed e' quindi pubblico: e' voluto e
non indebolisce niente, perche' la difficolta' non sta nel non sapere quali
parole ci sono ma in quante combinazioni ce ne siano. Se qualcuno lo sfoltisce
sotto le 200 parole, il programma si rifiuta di partire con un errore chiaro.

---

## D-031 — Il nome utente lo compone il programma, non la persona

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Alla creazione di un utente si scrivono nome, cognome e
indirizzo di posta. Il nome utente non si scrive: lo compone il programma nella
forma `nome.cognome`, tutto minuscolo, senza accenti e senza i caratteri che
non siano lettere o cifre, aggiungendo un numero progressivo (2, 3, ...) se
quel nome e' gia' di qualcun altro.

**Motivazione.** Se lo scrivesse la persona che crea l'utente, dopo sei mesi
nella stessa tabella convivrebbero tre convenzioni diverse: `mrossi`,
`m.rossi`, `rossi_mario`. Nessuna sarebbe sbagliata e nessuno saprebbe piu'
quale usare.

Gli accenti spariscono perche' un nome utente con l'accento dentro e' un nome
utente che prima o poi qualcuno scrive senza, e non riesce piu' a entrare.
Il numero progressivo comincia da 2 e non da 1: `mario.rossi1` farebbe pensare
che esista anche un `mario.rossi` senza numero da qualche parte.

**Conseguenza.** L'omonimia si verifica **anche contro gli utenti disattivati**.
Riusare il nome utente di chi ha lasciato l'azienda renderebbe ambigue tutte le
vecchie righe del registro delle operazioni, che continuerebbero a dire
"mario.rossi" riferendosi a una persona mentre le nuove ne indicano un'altra.

---

## D-032 — Lo stato dell'utente si rilegge dal database a ogni richiesta

**Data:** 24 agosto 2026 · **Stato:** attiva

**Decisione.** Nel cookie non c'e' niente all'infuori del gettone: nessun nome
utente, nessun ruolo, nessuna scadenza di cui fidarsi. A ogni richiesta si torna
al database a rileggere la sessione e la riga dell'utente, e si verificano di
nuovo `is_active`, `global_role` e `must_change_password`.

**Motivazione.** E' il requisito 11 della sessione 3, ed e' la differenza fra
"disattivare un utente" e "disattivare un utente **adesso**". Se il ruolo
viaggiasse dentro il cookie - firmato quanto si vuole - una persona a cui e'
stato tolto il ruolo di creatore continuerebbe ad averlo fino alla scadenza del
cookie, e una persona disattivata continuerebbe a lavorare fino a domani.

**Conseguenza.** Una interrogazione al database in piu' per ogni pagina. Per
qualche decina di utenti in rete locale e' irrilevante: e' una lettura per
chiave primaria su una tabella di poche righe, e la connessione e' gia' aperta
perche' la pagina dovra' comunque leggere qualcos'altro. Se un giorno il
programma dovesse servire numeri diversi, questa e' la decisione da rivedere per
prima - ed e' anche quella che non va rivista senza sostituirla con qualcosa che
garantisca la stessa immediatezza.

---

## D-033 — Un foglio di stile solo, con tutti i valori dichiarati in :root

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** L'intera grafica di Aurora sta in `app/static/css/aurora.css`:
un file solo, scritto a mano, diviso in sezioni numerate con un indice in cima.
Colori, spaziature, raggi e ombre sono dichiarati come variabili CSS nel blocco
`:root` e richiamati con `var(--nome)`. **Dentro una regola non si scrive mai un
valore esadecimale.**

**Motivazione.** Sul file unico: chi manterra' questo programma non conosce i
bundler e non deve conoscerli (regola 2 di CLAUDE.md). Con un file solo,
"dov'e' definito questo pulsante" ha una risposta sola e si trova con una
ricerca di testo. Diviso in file, servirebbe una regola su quale file importa
quale, e quella regola nessuno la scrive mai.

Sulle variabili: e' quello che rende possibile cambiare la tinta di tutto il
programma modificando una riga. Ed e' anche quello che rende verificabile il
contrasto: si controllano dieci combinazioni una volta, invece di ricontrollarle
a ogni pagina nuova.

**Conseguenza.** Il file cresce - e' gia' oltre le millecinquecento righe e
crescera' ancora. E' un prezzo accettabile finche' l'indice in cima resta
aggiornato: una sezione nuova va aggiunta anche li'.

Due test lo tengono in piedi: `test_i_colori_stanno_tutti_nelle_variabili`
fallisce se un colore compare fuori da `:root`, e
`test_nessun_colore_scritto_dentro_i_template` se ne compare uno dentro un
template. E' una regola che si viola per distrazione, copiando una riga, non
per scelta: per questo va verificata da un programma e non dalla buona volonta'.

---

## D-034 — I componenti sono macro Jinja2, e la vetrina /stile e' il contratto

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** Ogni pezzo ricorrente di interfaccia - pulsante, campo, tabella,
etichetta di stato, riquadro, finestra, notifica, ricerca, impaginazione,
schede, avanzamento, elenco descrittivo, area file, riquadro vuoto - e' un macro
Jinja2 in `app/templates/components/`. In cima a ogni file e' scritto **quando
si usa e quando non si usa**. Tutti insieme si vedono all'indirizzo `/stile`,
riservato al creatore.

Le pagine non riscrivono l'HTML di un componente a mano, nemmeno la vetrina.

**Motivazione.** Le sessioni da 5 a 13 costruiranno decine di pagine. Senza un
posto in cui i pezzi esistono gia', ogni sessione si porta dietro il proprio
pulsante e la propria tabella, e dopo tredici sessioni ce ne sono tredici
versioni leggermente diverse - nessuna delle quali si puo' correggere in un
punto solo.

Il commento "quando NON si usa" conta quanto l'altro. Sapere che esiste una
finestra modale porta a usarla; sapere che non ci si mette dentro niente di
indispensabile e' l'informazione che evita il guaio.

Sulla vetrina: e' l'unico modo perche' la documentazione non menta. Un elenco
scritto di componenti invecchia in tre settimane; una pagina che li disegna
passando dai macro veri non puo' invecchiare, perche' se un macro cambia la
pagina cambia con lui. Per questo la vetrina non riscrive l'HTML a mano: se lo
facesse, mostrerebbe una cosa che non esiste piu' - il modo peggiore possibile
di sbagliare, per una pagina il cui unico mestiere e' dire come stanno le cose.

**Conseguenza.** Aggiungere un componente vuol dire cinque passi, elencati in
`docs/GUIDA_STILE.md`, sezione 10. Uno di questi e' l'esempio in vetrina, e non
e' facoltativo: un componente che non e' in vetrina non lo trova nessuno e viene
riscritto da capo alla sessione successiva.

Un secondo effetto, scoperto scrivendoli: **i nomi dei macro devono essere
specifici.** I macro importati da una pagina finiscono nello stesso spazio delle
variabili con cui viene disegnato anche `base.html`, e un macro chiamato `menu`
copriva le voci della barra laterale. La pagina si apriva con un errore che non
diceva niente (`'Macro' object is not iterable`). Il menu a tendina si chiama
`tendina`.

---

## D-035 — Le voci della barra laterale stanno in Python, non nel template

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** Il menu di Aurora e' dichiarato in `app/navigation.py` come un
elenco di `VoceMenu`, ciascuna con etichetta, percorso, icona, se e' attiva e se
e' riservata al creatore. La funzione `pagina()` lo passa ai template gia'
filtrato per ruolo; il template lo disegna e basta.

Le sezioni non ancora realizzate compaiono nel menu **spente**, con la scritta
che dice in quale sessione arriveranno.

**Motivazione.** Il filtro per ruolo dentro l'HTML diventa illeggibile alla
terza condizione, e quali sezioni esistono e' un fatto del programma, non della
grafica. Quando la sessione 5 realizzera' i prodotti, bastera' togliere
`attiva=False` da una riga e la barra laterale si aggiornera' in tutte le pagine
insieme.

Sulle voci spente: mostrarle e' piu' onesto che nasconderle. Chi apre Aurora
oggi vede subito che cosa ci sara' e non si chiede se lo stia cercando nel posto
sbagliato. Sono `<span>` e non `<a>`: la tastiera non ci si ferma, perche' non
c'e' niente da aprire.

**Conseguenza da non fraintendere.** **Nascondere una voce non protegge
niente.** Il controllo che conta e' la dipendenza dichiarata sulla rotta
(`richiedi_login`, `richiedi_creatore`): quello e' il lucchetto. Il menu si
limita a non mostrare le porte che non si aprirebbero comunque, cosi' nessuno ci
va a sbattere.

---

## D-036 — HTMX e' un miglioramento, mai una condizione

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** HTMX 2.0.10 e' stato scaricato in
`app/static/vendor/htmx.min.js` e viene servito dal nostro programma. Ogni
pagina lo carica, ma **nessuna funzione di Aurora puo' dipendere da lui**: ogni
modulo e' un `<form>` normale che funziona da solo, e gli attributi `hx-` si
limitano a sostituire un pezzo di pagina invece di ricaricarla tutta.

Lo stesso vale per `app/static/js/aurora.js`: notifiche, finestre di dialogo e
trascinamento dei file sono tutti di piu' che spariscono senza far danni.

**Motivazione.** Tre ragioni, in ordine di importanza.

1. Un programma che custodisce il patrimonio documentale di un'azienda non deve
   smettere di funzionare perche' un file JavaScript non e' arrivato o perche'
   una politica aziendale lo blocca. Entrare e caricare un documento sono
   operazioni che devono riuscire sempre.
2. Un modulo GET che funziona da solo ha un indirizzo: la ricerca fatta si mette
   nei preferiti, si manda a un collega, si ritrova nella cronologia. E' una
   proprieta' che si perde nel momento in cui la ricerca esiste solo dentro
   JavaScript, e non si recupera piu'.
3. La verifica costa poco: il finto browser dei test non esegue JavaScript,
   quindi ogni test che passa e' anche la prova che quella pagina funziona senza.

**Conseguenza.** Ogni volta che si aggiunge un attributo `hx-`, va risposta una
domanda sola: che cosa succede se lo script non arriva? Se la risposta e' "non
funziona", quella non e' la strada. Il modello da copiare e' la barra di ricerca
della vetrina: un modulo GET verso `/stile`, piu' un `hx-get` verso il
frammento. Le due strade portano allo stesso posto.

Le finestre modali sono l'unico componente che ha davvero bisogno di JavaScript
per aprirsi. Per questo il commento in cima a `components/dialogo.html` dice di
non metterci dentro niente di indispensabile: la regola pratica e' "se la
finestra non si aprisse, l'utente resterebbe bloccato? Allora non e' una
finestra, e' una pagina".

---

## D-037 — Una pagina di errore sola, con tre presentazioni

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** `app/templates/errore.html` serve tutti i codici di errore.
Cambia la presentazione a seconda del codice: numero in tinta tenue per il 404
(un indirizzo sbagliato non e' colpa di nessuno), giallo per il 401 e il 403,
rosso per i guasti veri; e cambia il pulsante, che per il 401 porta all'accesso
e per tutti gli altri alla pagina iniziale.

**Motivazione.** La sessione 4 chiedeva "pagina di errore, pagina 404 e pagina
accesso negato coerenti con il tema". Tre file che dicono quasi la stessa cosa
si allontanano l'uno dall'altro alla prima modifica: dopo sei mesi il 404 e'
bello e il 403 e' rimasto indietro. Con un file solo, la coerenza non e' una
cosa da mantenere: e' una cosa che non si puo' rompere.

**Conseguenza.** Le pagine di errore usano `base_nudo.html`, senza barra
laterale: o non si e' entrati, o non si e' arrivati da nessuna parte. Mostrare
la navigazione a chi non e' entrato direbbe anche a un estraneo quali sezioni
esistono.

L'errore in HTML arriva solo a chi dichiara di accettare `text/html`; a un
programma risponde un JSON. E' il comportamento che c'era gia' dalla sessione 1,
e i test che guardano la pagina devono presentarsi come si presenta un browser -
altrimenti ricevono il JSON e non capiscono perche'.

---

## D-038 — La scomposizione del codice prodotto sta in un file di configurazione

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** La regola con cui si scompone un codice prodotto
(`RMS1100-24-110SW`) non e' scritta nel programma. Sta in un file TOML
indicato da `PRODUCT_CODE_CONFIG` nel file `.env`, che di partenza e'
`config/codice_prodotto.toml`. Dentro ci sono due cose:

- `espressione`, un'espressione regolare con **gruppi nominati**: ogni gruppo
  e' un elemento del codice, e il nome del gruppo diventa la chiave dentro
  `products.code_parts`;
- `[etichette]`, il nome in italiano di ciascun gruppo, quello che si legge
  nell'interfaccia.

L'ordine in cui gli elementi vengono mostrati e' l'ordine dei gruppi **dentro
l'espressione**, non quello delle etichette: e' l'ordine in cui compaiono nel
codice, ed e' l'unico che una persona guardando `RMS1100-24-110SW` riconosce.

L'ipotesi di partenza legge il codice come modello (`RMS`), potenza (`1100`),
tensione di ingresso (`24`), tensione di uscita (`110`), variante (`SW`).

**Motivazione.** Al momento in cui la sessione 5 e' stata fatta, **l'azienda
non aveva ancora confermato** come vanno letti i codici. Scrivere la regola
nel programma avrebbe voluto dire, il giorno della conferma, una modifica al
codice e un rilascio; scrivendola in un file, quel giorno si cambia una riga
di testo e si riavvia il server.

La stessa scelta regge anche il caso piu' probabile di tutti: che la regola
non sia una sola. Se domani i codici di una famiglia di prodotti si leggessero
in un altro modo, l'espressione la si allarga senza toccare il programma.

**Conseguenza.** Nessun template e nessuna rotta sa quanti sono gli elementi
di un codice. I filtri della ricerca dei prodotti si costruiscono sugli
elementi che la regola dichiara: se domani ce ne sara' uno in piu', comparira'
una tendina in piu' senza che nessuno tocchi una riga di HTML.

`products.riscomponi()` ricalcola `code_parts` con la regola in uso adesso.
Non e' ancora richiamata da nessuna pagina - lo sara' con la pagina di
diagnostica, sessione 11 - ma esiste perche' il giorno della conferma i
prodotti gia' inseriti vanno riportati alla regola nuova, e la strada deve
essere gia' aperta.

---

## D-039 — Un codice non riconosciuto si accetta, non si rifiuta

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** Un codice prodotto che non corrisponde alla regola di
scomposizione **viene accettato lo stesso**: il prodotto si crea con
`code_parts` vuoto e chi lo ha inserito trova un avviso visibile che glielo
dice. Non esiste, in nessun punto del programma, un controllo sulla forma di
un codice prodotto.

Vale anche per il file di configurazione: se manca, se non si legge o se
contiene un'espressione sbagliata, Aurora **parte lo stesso** e si comporta
come se nessun codice fosse riconoscibile. Il guasto finisce nel registro e
compare come avviso in cima all'elenco dei prodotti e nel modulo di
creazione, ma non ferma niente.

**Motivazione.** E' un requisito esplicito dell'azienda, e la ragione per cui
lo ha chiesto e' la stessa per cui la regola non e' confermata: **i codici
veri sono gia' li'**, in anni di listini, e qualcuno di loro non seguira'
nessuna regola. Un programma che li rifiuta e' un programma in cui quei
prodotti non si possono inserire, e la conseguenza non e' che i codici
migliorano: e' che quel prodotto resta su un foglio di calcolo.

Sul file di configurazione rotto vale un ragionamento parallelo. La regola 8
di CLAUDE.md vuole che un parametro obbligatorio mancante fermi l'avvio, ed e'
giusto per la stringa di connessione al database: senza, il programma non fa
niente comunque. Qui no: senza scomposizione Aurora perde **una comodita' di
ricerca** e continua a custodire i documenti. Far cadere tutto il programma
per un errore di battitura in un'espressione regolare vorrebbe dire che
chiunque tocchi quel file puo' chiudere fuori l'azienda intera.

**Conseguenza.** `product_codes.scomponi()` non solleva mai e non rifiuta mai:
restituisce un dizionario, eventualmente vuoto. Il test
`test_un_codice_non_riconosciuto_viene_accettato_lo_stesso` esiste apposta per
impedire che qualcuno, in buona fede, aggiunga una validazione.

---

## D-040 — Un prodotto nasce sempre con la sua versione 1

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** `products.crea_prodotto()` crea il prodotto **e** la sua
versione 1, in una transazione sola, e restituisce tutti e due. Non esiste un
modo di creare un prodotto senza versioni. La versione 1 non discende da
niente (`derived_from_id` nullo) e parte da `in_sviluppo`.

**Motivazione.** Un prodotto senza versioni non e' niente su cui si possa
lavorare: non ci si apre un progetto, non ci si attaccano documenti, non ci si
manda posta. Sarebbe una riga a meta', e le righe a meta' nel database sono
quelle che sei mesi dopo fanno sbagliare un conteggio - "quanti prodotti
abbiamo?" - senza che nessuno capisca perche'.

**Conseguenza.** Il modulo di creazione di un prodotto non chiede niente sulla
versione: non c'e' niente da chiedere. La versione 2 arriva sempre per
derivazione, da una pagina diversa, e li' la motivazione e' obbligatoria.

---

## D-041 — Il modello di fasi si congela nel progetto

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** Alla nascita, un progetto si tiene l'identificatore del modello
di fasi scelto e **copia dentro di se'** le norme applicabili
(`projects.standards`). Da quel momento nessuna modifica al modello tocca il
progetto. Il progetto entra subito nella prima fase del modello.

**Motivazione.** I modelli di fasi sono gia' immutabili per costruzione - una
correzione diventa una versione nuova del modello, vedi
`docs/MODELLO_DATI.md` 4.7 - quindi il solo legame basterebbe a garantire che
le fasi non cambino. La copia serve per le **norme**, che invece sul singolo
progetto si possono allargare o restringere: partono da quelle del modello e
poi vivono di vita propria.

Il principio e' quello dei documenti e delle versioni di prodotto: un progetto
aperto due anni fa deve raccontare le fasi e le norme **di allora**. Se le
leggesse dal modello di adesso, la sua storia parlerebbe di passaggi che al
tempo non esistevano, e le approvazioni registrate risulterebbero riferite a
fasi mai attraversate.

**Conseguenza.** Un modello disattivato non si propone piu' per i progetti
nuovi ma continua a valere per quelli che lo stanno usando. Il test
`test_il_modello_di_fasi_resta_congelato_nel_progetto` disattiva il modello e
verifica che il progetto non se ne accorga.

Insieme al progetto viene scritta anche la riga di registro dell'**ingresso
nella prima fase** (`project.phase_entered`). E' un fatto che succede adesso:
se non lo si scrivesse, la storia delle fasi comincerebbe dal secondo
passaggio e nessuno saprebbe piu' quando il progetto e' entrato nel primo. La
richiesta e l'approvazione dei passaggi successivi sono lavoro della
sessione 6.

---

## D-042 — Il grafo delle transizioni sta in un posto solo, e il superamento e' automatico

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** Le transizioni ammesse fra gli stati del ciclo di vita di una
versione sono dichiarate in **una tabella sola**, `TRANSIZIONI_AMMESSE` in
`app/services/lifecycle.py`:

```
in sviluppo --> rilasciato --> in produzione
                    |                |
                    +--> superato <--+
                             |
      (da ogni stato) --> obsoleto
```

Non si torna mai indietro; a `superato` si arriva anche a mano; `obsoleto` e'
l'unico stato terminale. Una transizione fuori dal grafo viene rifiutata con
una frase italiana che dice **quali sono quelle possibili**.

Sopra al grafo stanno tre regole:

1. **Superamento automatico.** Quando una versione passa a `rilasciato`, la
   versione precedente dello stesso prodotto passa da sola a `superato`, e
   l'operazione viene registrata **come azione di sistema**: la riga di audit
   ha `user_id` nullo.
2. **Conferma prima di procedere.** Il passaggio si esegue da una pagina di
   conferma - non da una finestra modale - che dice quale versione verra'
   superata, con il suo numero e il suo stato di adesso.
3. **`obsoleto` vuole una motivazione**, scritta a mano, che finisce in
   `audit_logs.new_value`.

Il cambio di stato e' riservato al **creatore** e al **project manager** del
progetto aperto su quella versione. Una versione su cui non e' ancora stato
aperto nessun progetto la muove solo il creatore, perche' non c'e' ancora
nessun responsabile a cui la decisione appartenga.

**Motivazione.** Sul grafo in un punto solo: le regole di passaggio sono la
parte del programma che l'azienda cambiera' piu' spesso, ed e' anche quella
che, sparsa in venti `if`, diventa impossibile da rileggere. Cosi' invece si
apre un file, si guardano dieci righe e si sa tutto.

Sull'autore nullo del superamento: chi ha premuto il pulsante ha **rilasciato
la versione nuova**, non ha superato la vecchia. Scriverci il suo nome direbbe
una cosa falsa, e fra un anno, leggendo il registro, non si distinguerebbe
piu' una decisione presa da una persona da una conseguenza calcolata dal
programma. E' esattamente il caso che `docs/MODELLO_DATI.md` prevedeva quando
ha reso `audit_logs.user_id` facoltativo.

Sulla conferma come pagina e non come finestra: rilasciare una versione ne
cambia un'altra, e chi preme deve poter leggere prima che cosa succedera'. Una
finestra modale ha bisogno di JavaScript per aprirsi; se non si aprisse,
l'operazione partirebbe senza che nessuno abbia letto niente (D-036 e la
regola in `docs/GUIDA_STILE.md`).

**Conseguenza.** Il grafo vale **anche per le operazioni che fa il programma
da solo**: se la versione precedente e' in uno stato da cui non si puo' andare
a `superato` (per esempio gia' obsoleta), il superamento automatico la salta e
la pagina di conferma lo dice. Senza questa regola, il programma avrebbe una
strada per mettere una versione in uno stato che il grafo vieta, e il grafo
smetterebbe di essere la verita'.

Le pagine costruiscono i pulsanti su `stati_raggiungibili()`: non si propone
mai un'operazione che verrebbe poi rifiutata, e cambiando il grafo cambiano
anche i pulsanti senza toccare nessun template.

---

## D-043 — Chi non e' assegnato a un progetto non lo vede

**Data:** 25 agosto 2026 · **Stato:** attiva, tranne l'ultimo paragrafo,
**superato da D-052**

**Decisione.** Il cruscotto e l'elenco dei progetti mostrano solo i progetti
su cui chi guarda ha un'**assegnazione non revocata**. Il filtro e'
nell'interrogazione (`_progetti_visibili()` in `app/services/projects.py`), non
nel template. La stessa regola vale per la scheda del singolo progetto: chi non
lo vedrebbe nell'elenco riceve un 403 anche scrivendone l'indirizzo.

Il **creatore vede tutto**, perche' e' lui che apre i progetti e assegna le
persone. Il **project manager e' anche un assegnato**: l'apertura del progetto
gli scrive la sua riga in `assignments`.

**Motivazione.** Sul filtro nell'interrogazione: un elenco che nasconde una
riga che poi si apre scrivendone l'indirizzo non e' una protezione, e' una
tenda. Le due strade devono dare la stessa risposta, e il modo per esserne
certi e' che sia la stessa funzione a rispondere.

Sul project manager assegnato: senza quella riga, "chi vede questo progetto"
avrebbe due risposte - chi ha un'assegnazione, **piu'** il responsabile - e
ogni interrogazione futura dovrebbe ricordarsi del secondo caso. E' lo stesso
principio di D-032: **un controllo solo, sulla strada obbligata.**

**Conseguenza.** Una persona ha al massimo un ruolo attivo per progetto: e' il
vincolo dell'indice parziale su `assignments`, e `projects.assegna()` lo
rispetta revocando quella precedente invece di aggiungerne una seconda. La
riga revocata resta in tabella con la sua data: "chi aveva accesso a questo
progetto in marzo" e' una domanda a cui si deve poter rispondere.

~~Il 404 e il 403 restano distinti: "non esiste" e "esiste ma non e' tuo" sono
due cose diverse. Nascondere la seconda dietro la prima sembra piu' prudente,
ma manda chi ha davvero bisogno di quel progetto a cercare un guasto che non
c'e', invece che a chiedere l'assegnazione.~~

**Superato da D-052** (25 agosto 2026, sessione 7): un progetto che non si puo'
vedere risponde **404**, con lo stesso messaggio di uno che non esiste. Il
ragionamento qui sopra vale per chi si e' perso, ma non per chi prova gli
indirizzi uno per uno: per lui la differenza fra le due risposte e' l'elenco
dei progetti dell'azienda.

---

## D-044 — I due cicli di vita stanno tutti e due in `lifecycle.py`

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** Il grafo degli stati di un **documento** (`bozza`,
`in verifica`, `rilasciato`, `superato`) sta in `app/services/lifecycle.py`,
accanto a quello delle versioni di prodotto, nella tabella
`TRANSIZIONI_DOCUMENTO`:

```
bozza <--> in verifica --> rilasciato --> superato
  ^                             |
  +---- (si carica una versione nuova) --+
```

Non si torna indietro da `rilasciato`, `superato` e' terminale, e da
`in verifica` si torna in bozza perche' quello e' il rifiuto della verifica.

**Motivazione.** Il posto naturale sarebbe `documents.py`, dove sta tutto il
resto dei documenti. Metterlo li' avrebbe pero' rotto la regola che D-042 ha
appena stabilito e che CLAUDE.md ripete fra le cose da non fare mai: **due
stati non si confrontano fuori da `lifecycle.py`**. Con un grafo in un file e
uno in un altro, la regola diventa "i grafi stanno un po' dove capita", e alla
terza sessione ce n'e' un terzo.

Il nome del modulo regge: si chiama `lifecycle`, non `product_lifecycle`.

**Conseguenza.** `documents.py` importa `lifecycle` e non decide niente sugli
stati: chiama `verifica_transizione_documento()` e lascia che sia quella a
rifiutare. La docstring in cima a `lifecycle.py` adesso dichiara che i cicli
di vita sono due e dove comincia il secondo.

---

## D-045 — Il rilasciato non si sostituisce, e la regola non e' un divieto

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** Un documento in stato `rilasciato` non puo' avere il proprio
file sostituito. Caricando un file su quel documento si crea la **versione
successiva**, e il documento torna in `bozza`. La versione rilasciata resta in
tabella con la sua impronta, e il suo file nell'archivio non viene toccato.

Il ritorno in bozza **non e' una transizione del grafo**: nessuno preme un
pulsante "torna in bozza". E' la conseguenza del caricamento, e sta scritta in
`documents.aggiungi_versione()`.

**Motivazione.** Il criterio di accettazione dell'azienda dice che
"l'interfaccia lo impedisce e propone la nuova versione". Si poteva
rispondere in due modi: un controllo che rifiuta la sostituzione, oppure un
programma in cui sostituire un file non e' un'operazione che esiste. Il
secondo e' piu' robusto, perche' non c'e' nessun controllo che qualcuno possa
dimenticare di scrivere sulla strada nuova che aprira' fra tre sessioni: le
righe di `document_versions` non si modificano e basta, e l'unica cosa che si
puo' fare a un documento e' aggiungergliene una.

Sul ritorno in bozza: una versione nuova non e' verificata da nessuno, quindi
lasciare il documento "rilasciato" direbbe una cosa falsa. Deve rifare il giro.

**Conseguenza.** La pagina del caricamento di una versione, quando il
documento e' rilasciato, spiega tutto questo **prima** del modulo. Il
passaggio a rilasciato ha la sua pagina di conferma, che dice che da li' in
poi il file non si sostituira' piu', e viene registrato con autore e data.

L'autore e la data del rilascio non hanno una colonna in `documents`: si
rileggono dal registro delle operazioni con `documents.ultimo_rilascio()`.
Duplicarli in una colonna vorrebbe dire due verita' che possono divergere, e
il registro e' gia' il posto in cui i fatti vengono registrati (regola 6 di
CLAUDE.md).

---

## D-046 — La filigrana si applica al volo, e se fallisce il file esce lo stesso

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** Quando si scarica un PDF che appartiene a una versione di
prodotto in stato `superato` o `obsoleto`, il file viene marchiato **al
momento del download**, su una copia in memoria, con una filigrana diagonale
che dice la dicitura, lo stato e il momento dello scarico. L'originale
nell'archivio non viene toccato.

Per i formati che non si possono marchiare senza rovinarli, l'avvertenza
viaggia in due altri modi: una **pagina di avviso** prima dello scarico e
l'avvertenza dentro il **nome del file** consegnato.

Se pypdf non riesce ad aprire o a riscrivere il PDF, l'errore viene registrato
con la sua traccia e **il file viene consegnato com'e'**, con l'avvertenza nel
nome.

**Motivazione.** Sul marchiare al volo invece che alla scrittura: il file
depositato deve restare identico a quello caricato, perche' e' la sua impronta
a dimostrare che un documento approvato non e' stato alterato (D-004). Un file
marchiato all'ingresso avrebbe un'impronta diversa da quella del file che
l'ingegnere ha firmato. In piu' la data e l'ora dello scarico, che sono la
parte utile della filigrana, all'ingresso non si conoscono.

Sul non rifiutare il download: togliere a una persona un documento che ha il
diritto di avere, per un guasto in un PDF che non la riguarda, e' il modo
peggiore di sbagliare. L'avvertenza resta comunque nel nome del file, e chi
amministra trova la riga nel registro.

Sull'avviso a schermo come pagina e non come finestra modale: se lo script non
arrivasse, la finestra non si aprirebbe e il file partirebbe lo stesso - che e'
esattamente quello che l'avviso serve a evitare (D-036).

**Conseguenza.** `pypdf` entra in `requirements.txt`. E' una libreria che
lavora solo in memoria, non parla con nessun servizio esterno e non ha
dipendenze native: il vincolo "deve funzionare con internet staccato" regge.

Il dirottamento verso la pagina di avviso sta **nella rotta dello scarico** e
non nei collegamenti, cosi' vale per tutti i modi in cui ci si arriva: il
pulsante, un indirizzo copiato, un preferito salvato sei mesi fa.

---

## D-047 — L'archivio scrive su un temporaneo e rinomina

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** Un file caricato viene scritto in
`STORAGE_PATH/tmp/<casuale>.parziale`, con l'impronta SHA-256 calcolata
**mentre** si scrive, e solo a scrittura completata - dopo un `fsync` - viene
spostato al suo posto definitivo con `os.replace()`. Se il contenuto e' gia'
nell'archivio, il temporaneo viene buttato e non si riscrive niente.

Il limite di dimensione (`MAX_UPLOAD_MB`, 2 GB di partenza) si verifica
durante la lettura, non dopo.

**Motivazione.** `os.replace()` e' atomico a livello di sistema operativo: da
quel momento il file c'e' per intero o non c'e' affatto. Senza, un'interruzione
a meta' caricamento lascerebbe al posto giusto un file troncato che **sembra
buono**, e sarebbe il caso peggiore di tutti: la deduplicazione lo
riconoscerebbe come gia' presente e nessuno riscriverebbe mai quello vero.

Il temporaneo sta **dentro** `STORAGE_PATH` e non nella cartella temporanea di
sistema perche' `os.replace()` e' atomico solo dentro lo stesso volume: in
produzione l'archivio sta su un disco dedicato, e uno spostamento fra volumi
diversi e' una copia, non uno scambio di nome.

Il `fsync` prima dello spostamento serve contro un'interruzione di corrente
subito dopo: senza, il sistema operativo potrebbe aver spostato il nome senza
aver ancora scritto i byte.

Il limite verificato durante la lettura serve a non far riempire il disco da un
file che verra' comunque rifiutato.

**Conseguenza.** Un temporaneo rimasto in `storage/tmp/` vuol dire un
caricamento interrotto: non e' riferito da nessuna riga del database e si puo'
togliere senza perdere niente. `storage.temporanei_rimasti()` esiste per i
test e per la pagina di diagnostica della sessione 11.

Una transazione annullata dopo che il file e' stato depositato lascia
nell'archivio un oggetto che nessuno riferisce. Non e' un problema: non si
cancella (regola 5), e al primo caricamento dello stesso contenuto la
deduplicazione lo riusa.

---

## D-048 — I permessi sui documenti si leggono dalla matrice, in un posto solo

**Data:** 25 agosto 2026 · **Stato:** attiva, **estesa da D-051**

**Decisione.** Chi puo' vedere, caricare e modificare un documento lo dice la
casella di `permission_rules` all'incrocio fra il **ruolo che la persona ha in
quel progetto** e la **classificazione del documento**.
`app/services/permissions.py` e' l'unico posto in cui quella tabella viene
consultata, e offre la stessa regola in due forme: `permessi()` per un
documento solo, `filtro_visibilita()` come condizione SQL per gli elenchi.

Una casella che manca vale **no**, e il fatto finisce nel registro. Il
creatore vede e puo' tutto.

**Motivazione.** Le due forme sono due scritture della stessa domanda, e
questo e' il punto: un elenco che nasconde una riga che poi si apre
scrivendone l'indirizzo non e' una protezione, e' una tenda (D-043). Perche'
le due strade diano sempre la stessa risposta devono partire dalla stessa
tabella e stare nello stesso file, dove chi cambia una si accorge dell'altra.

Sulla casella mancante che vale no: e' l'unico modo prudente di sbagliare. Il
contrario vorrebbe dire che aggiungendo una classificazione nuova si aprono
per sbaglio dei documenti a chi non doveva vederli.

**Conseguenza.** Il menu a tendina della classificazione, nella pagina di
caricamento, propone **solo** le classificazioni con cui quella persona puo'
davvero caricare: proporne una con cui il caricamento verrebbe poi rifiutato
vuol dire far perdere a qualcuno l'attesa di un file da 300 MB.

~~**La matrice non si modifica dall'interfaccia.** Questa sessione la legge e
basta: la pagina che la corregge e' rimasta in sospeso dalla sessione 3 ed e'
segnata in `docs/STATO.md`. Fino ad allora la matrice e' quella scritta da
`scripts/seed.py`.~~

**Fatto nella sessione 7**: la matrice si corregge da `/permessi`, con una
conferma e una riga di registro per casella. Nella stessa sessione D-051 ha
allargato il principio di questa decisione a **tutti** i permessi di Aurora, e
`permessi()` e `filtro_visibilita()` sono diventate `puo()`, `pretendi()`,
`filtro_documenti()` e `filtro_progetti()`.

---

## D-049 — Un file caricato, un documento; il titolo cede al nome del file

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** Scegliendo piu' file insieme si creano **piu' documenti, uno
per file**. Il titolo scritto nel modulo vale quando il file e' uno solo;
negli altri casi ogni documento prende come titolo il nome del proprio file,
senza estensione. Tipo e classificazione valgono per tutti.

**Motivazione.** La sessione chiede di poter caricare "uno o piu' file
insieme" e, separatamente, di indicare un titolo. Le due cose insieme non
stanno in piedi: con dieci file non esiste un titolo solo che vada bene per
tutti, e chiederne dieci in un modulo vorrebbe dire un modulo che si compila
in cinque minuti.

Un documento per file e' anche la lettura giusta del modello: il documento e'
il contenitore di **una** cosa che nel tempo cambia versione. Dieci file
insieme sono dieci cose diverse, non dieci versioni della stessa.

**Conseguenza.** Chi carica dieci schemi ha dieci documenti con il titolo del
file, e li rinomina dopo se vuole. Intanto i file sono dentro, che e' quello
che conta: un caricamento che si rifiuta perche' manca un titolo e' un
caricamento da rifare.

La regola sta in `documents.crea_documento()` e non nella rotta: e' una regola,
e le regole si provano con un test.

---

## D-050 — L'elenco dei tipi di documento sta in un file di configurazione

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** I tipi di documento proponibili al caricamento (Schema
elettrico, PCB, Meccanica, Firmware, Specifica, Rapporto di prova,
Certificato, Corrispondenza, Altro) stanno in `config/tipi_documento.toml`,
indicato da `DOCUMENT_TYPES_CONFIG` nel file `.env`. Se il file manca o e'
scritto male, Aurora parte lo stesso e usa l'elenco di ripiego scritto in
`app/services/doc_types.py`.

**Motivazione.** E' la stessa scelta di D-038 per la scomposizione dei codici
prodotto, e per la stessa ragione: e' un elenco che l'azienda cambiera'
- aggiungera' "Analisi FMEA", togliera' quello che non usa - e cambiarlo non
deve voler dire una modifica al programma e un rilascio.

Il ripiego che non ferma il programma e' D-039 applicato ai tipi: un errore di
battitura in un file di configurazione non deve poter impedire a tutta
l'azienda di caricare i documenti.

**Conseguenza.** `documents.doc_type` resta una colonna di testo e non diventa
una chiave esterna: togliendo una voce dal file, i documenti che l'avevano
continuano a mostrare il loro tipo, semplicemente non lo si puo' piu' scegliere
per un documento nuovo. E' la regola generale del modello - un dato scritto nel
database si mostra sempre, anche quando non lo si sa piu' spiegare.

---

## D-051 — Un solo punto decide i permessi: `permissions.puo()`

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** Tutte le domande di permesso di Aurora passano da una funzione
sola:

```python
permissions.puo(db, utente, Azione.VEDERE, documento)
```

Non ci sono altre strade. La funzione tratta cinque tipi di oggetto - un
documento, un bersaglio di caricamento (progetto + classificazione), un
progetto, una versione di prodotto e la sentinella `AMMINISTRAZIONE` per le
sezioni riservate al creatore - e su un oggetto che non conosce risponde
**no**, scrivendolo nel registro.

Da questa decisione discendono quattro cose:

- `projects.puo_vedere()` e `lifecycle.puo_cambiare_stato()` **non esistono
  piu'**: erano la stessa domanda posta in due file che parlano d'altro;
- `richiedi_creatore` non confronta piu' un ruolo: chiede a `puo()`;
- `navigation.voci_visibili()` non guarda piu' il ruolo di nessuno: riceve la
  risposta gia' fatta;
- **nei template non c'e' piu' nessuna verifica di permesso.** Le pagine
  ricevono booleani gia' decisi (`puo_amministrare`, `permessi.caricare`) e li
  usano per sapere se disegnare un pulsante.

`filtro_documenti()` e `filtro_progetti()` sono la stessa regola scritta come
condizione SQL per gli elenchi, e stanno nello stesso file a poche righe di
distanza.

**Motivazione.** Le regole di accesso sbagliate non si vedono. Un elenco che
mostra una riga di troppo sembra un elenco normale, e chi lo guarda non ha modo
di accorgersene: non c'e' nessuna schermata rossa, nessun errore nel registro,
nessun utente che si lamenta - anzi, chi ne approfitta sta zitto. E' l'esatto
contrario di un difetto di calcolo, che salta fuori il primo giorno.

L'unica difesa contro un difetto che non si vede e' che la regola stia in un
punto solo, dove si legge tutta insieme e dove un test la puo' esercitare in
tutte le sue combinazioni. Con la regola sparsa in sei file, la domanda "chi
vede i documenti commerciali?" ha sei risposte che si possono contraddire, e
nessun modo di accorgersene se non provandole tutte.

Sulle due forme - `puo()` e i filtri SQL - vale quello che diceva gia' D-048:
sono due scritture della stessa domanda, e devono partire dalla stessa tabella
nello stesso file, dove chi cambia una si accorge dell'altra. La sessione 7
aggiunge la verifica: `tests/test_permessi.py` le confronta su tutte le
combinazioni di ruolo, classificazione e azione, e controlla anche il
**conteggio** - un documento nascosto che comparisse nel totale direbbe il
numero esatto delle cose che non si dovrebbero sapere.

Sui template: un `{% if utente.is_creatore %}` dentro una pagina e' la peggiore
delle verifiche di permesso, perche' non protegge niente - la rotta si apre lo
stesso scrivendone l'indirizzo - e sembra che protegga. Toglierli tutti serve
anche a un secondo scopo: quello che resta in un template si legge come
disegno, e un `{% if %}` che riapparisse si noterebbe.

**Conseguenza.** Quattro test di `tests/test_permessi.py` non guardano il
comportamento ma **leggono i sorgenti**: nessun file fuori da `permissions.py`
interroga `permission_rules`, nessuna rotta guarda `is_creatore` o
`global_role`, nessun template contiene una di quelle parole, e ogni router che
tocca i permessi nomina `permissions`. Sono test di forma, e le regole di forma
senza un test durano fino alla prossima fretta.

L'etichetta del ruolo globale, dove va **mostrata**, si compone in
`users.ruolo_mostrato()`: e' testo e un colore, non un permesso, e passa dal
servizio per la stessa regola di CLAUDE.md per cui un menu a tendina si compone
in Python.

---

## D-052 — Quello che non si puo' vedere risponde 404, non 403

**Data:** 25 agosto 2026 · **Stato:** attiva · **supera in parte D-043**

**Decisione.** Chiedendo un documento, un progetto o una versione che la
persona **non ha il permesso di vedere**, Aurora risponde **404** con lo stesso
messaggio, parola per parola, che avrebbe dato per un identificativo
inesistente. Il **403** resta per il caso diverso: l'oggetto lo si vede gia' e
manca il permesso per quella operazione - cambiarne lo stato, caricare una
versione, ritirarlo. La distinzione la fa `permissions.pretendi()`, in un punto
solo.

Un bersaglio di caricamento riceve sempre 403 e mai 404: e' un progetto piu'
una classificazione, e nessuno dei due e' un segreto.

**Motivazione.** D-043 aveva scelto il 403 anche per il primo caso, con
l'argomento che "non esiste" e "esiste ma non e' tuo" sono due cose diverse e
che nasconderle una dietro l'altra manda chi ha davvero bisogno di quel
documento a cercare un guasto invece che a chiedere il permesso. L'argomento e'
giusto per chi si e' perso, ma non regge davanti a chi non si e' perso affatto:
il 403 e' una risposta che **conferma**. Chi prova mille identificativi di fila
e guarda quali rispondono 403 e quali 404 si costruisce l'elenco di quello che
non deve sapere - quali codici sono stati assegnati, quanti progetti sono
aperti, quando ne nasce uno nuovo - senza vederne nemmeno uno.

Il messaggio dev'essere identico e non soltanto simile, ed e' il motivo per cui
sta in `permissions.py` e non nelle rotte: due frasi scritte in due posti
diversi finiscono per differire di una virgola, e quella virgola dice tutto.

**Conseguenza.** Il paragrafo finale di D-043 e' superato. Chi ha davvero
bisogno di un documento che riceve 404 lo scoprira' chiedendo, e chi lo
amministra ha la pagina di **verifica accessi** (`/utenti/{id}/accessi`) per
rispondergli senza dover entrare con le sue credenziali.

---

## D-053 — Il project manager puo' tutto sui documenti del suo progetto

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** Chi e' scritto in `projects.project_manager_id` ha accesso
completo a **tutti** i documenti di quel progetto, qualunque cosa dica la
matrice. L'eccezione vale per il **responsabile di quel progetto**, non per
chiunque abbia il ruolo di progetto `project_manager`: per quest'ultimo decide
la matrice, come per tutti gli altri.

**Motivazione.** Il responsabile di un progetto risponde di tutto quello che
c'e' dentro, comprese le offerte, i contratti e la corrispondenza commerciale.
Una matrice che gli nascondesse un documento del suo progetto sarebbe una
matrice sbagliata, e il modo di scoprirlo sarebbe una telefonata il giorno in
cui serve il documento.

Sulla distinzione fra "il responsabile" e "chi ha quel ruolo": se bastasse
avere il ruolo `project_manager` in un progetto per passare sopra le caselle,
la riga `project_manager` della griglia non deciderebbe piu' niente, e chi la
corregge lo farebbe a vuoto senza che nessuno glielo dica. Una casella che non
governa niente e' peggio di una casella che manca.

**Conseguenza.** L'eccezione e' scritta due volte, come tutte le regole di
accesso: dentro `puo()` e dentro `filtro_documenti()`, dove diventa il primo
dei due `EXISTS`. C'e' un test che verifica che le due scritture concordino, e
uno che verifica che un secondo project manager assegnato al progetto segua
invece la matrice.

---

## D-054 — Una classificazione si disattiva, e solo se non e' in uso

**Data:** 25 agosto 2026 · **Stato:** attiva

**Decisione.** `classifications` prende la colonna `is_active` (migrazione
`b1c4e2af7d30`). Una classificazione che non serve piu' si **disattiva**:
sparisce dai menu a tendina e dai filtri, la riga resta in tabella con le sue
caselle della matrice, e si puo' riattivare. Non si cancella, come niente in
Aurora (regola 5 di CLAUDE.md).

La disattivazione e' **rifiutata** se almeno un documento ha quella
classificazione, ritirati compresi. E una classificazione disattivata **non
accetta caricamenti nuovi**, nemmeno da una richiesta scritta a mano.

**Motivazione.** La classificazione e' meta' della coppia che decide chi vede
un documento: toglierla a un documento vorrebbe dire lasciarlo senza la riga
che risponde a quella domanda, e un documento di cui non si sa piu' chi lo puo'
vedere e' un documento che nessuno sa piu' se mostrare.

Le due regole insieme danno un'invariante che vale la pena di scrivere:
**disattivata vuol dire vuota per sempre**. Si disattiva solo quello che non e'
in uso, e da quel momento non ci finisce dentro piu' niente. E' questa
invariante che permette alla griglia dei permessi di smettere di mostrare le
classificazioni disattivate senza nascondere niente: le loro caselle non
governano piu' nessun documento, e non ne governeranno.

**Conseguenza.** I documenti ritirati si contano insieme agli altri quando si
guarda se una classificazione e' in uso. Un ritirato non e' sparito, e' solo
fuori dagli elenchi: se lo si ripristinasse e la sua classificazione non ci
fosse piu', si ricadrebbe esattamente nel caso che questa decisione evita.

---

## D-055 — Le fasi sono dati: il comportamento sta in una colonna, non in un `if`

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** Il programma non sa come si chiamano le fasi. Aggiungere una
fase, rinominarla, riordinarla o costruire un percorso completamente diverso si
fa dall'interfaccia (`/fasi`) e non costa nessuna riga di codice.

Le due fasi che si comportano in modo particolare portano il loro comportamento
addosso, come colonne di `phases` (migrazione `c7a3f19b52e4`):

| Colonna | Che cosa dice |
|---|---|
| `blocks_return` | da questa fase non si torna a una precedente |
| `closes_project` | entrando in questa fase, `projects.closed_at` viene valorizzato |

Le spunte le mette chi crea il modello, e il modulo pretende che ce ne sia
**una e una sola** che chiude, e che sia **l'ultima**.

**Motivazione.** La sessione 8 chiedeva due regole che parlano di fasi precise:
"da Development non si torna indietro" e "la fase finale chiude il progetto".
Scritte come sono enunciate diventano due `if` sul nome di una fase, e da quel
momento rinominare "Development" sarebbe una modifica al programma - con un
progetto aperto due anni fa che continua a chiamarla in un altro modo e che
quindi non seguirebbe piu' la stessa regola. Le fasi sono dati; una regola che
parla di dati deve stare nei dati.

C'e' un **test che legge i sorgenti** (`test_fasi.py`,
`test_nessun_file_del_programma_confronta_il_nome_di_una_fase`) e diventa rosso
se in `app/` ricompare uno dei nomi veri delle fasi come stringa usata dal
programma. Guarda l'albero sintattico e non il testo, cosi' le docstring che
citano "Concept" come esempio restano lecite. Ce n'e' un secondo per i
template, che cerca i confronti su `.name`.

**Conseguenza.** I nomi veri delle fasi compaiono in due posti soli, e tutti e
due sono dati: `scripts/seed.py`, che li scrive, e la migrazione
`c7a3f19b52e4`, che ha tradotto in spunte la regola che fino a ieri non era
scritta da nessuna parte. Il commento della migrazione lo dice per esteso,
perche' e' l'unico posto di Aurora in cui un nome di fase compare accanto a una
condizione.

Il divieto di tornare indietro **non e' un permesso**: sta in
`phases.torna_a()` e vale anche per il creatore. Un creatore che potesse
riavvolgere un progetto in costruzione riscriverebbe una storia avvenuta, che e'
proprio quello che nessun ruolo deve poter fare.

---

## D-056 — Chi lavora al progetto chiede, chi lo governa decide

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** `Azione` prende un quinto valore, `RICHIEDERE`, e
`permissions.puo()` lo decide cosi' su un progetto:

| Chi | Che cosa puo' |
|---|---|
| il **creatore** | tutto, come sempre |
| il **project manager** del progetto | avanzare, tornare indietro, decidere le richieste altrui (`MODIFICARE`) |
| chi e' **assegnato** al progetto e non lo governa | **chiedere** l'avanzamento (`RICHIEDERE`) |
| tutti gli altri | niente: il progetto non lo vedono nemmeno |

**Motivazione.** La sessione dice "l'ingegnere puo' richiedere l'avanzamento".
Il permesso e' stato scritto come "chi e' nella squadra e non e' il
responsabile" e non come "chi ha il ruolo di progetto `ingegnere`", per due
ragioni. La prima e' che i ruoli di progetto sono governati dalla matrice dei
permessi, che parla di **documenti**: aggiungerci un significato che riguarda
le fasi vorrebbe dire due tabelle di ruoli da tenere allineate. La seconda e'
che una richiesta non cambia niente da sola - la decide il responsabile -
quindi allargarla a chi e' assegnato non apre nessuna porta.

`RICHIEDERE` e `AMMINISTRARE` sono le due azioni che **non** sono colonne della
matrice: `Permessi.consente()` risponde "no" a tutte e due, perche' nessuna
delle due parla di documenti.

**Conseguenza.** Il project manager non puo' "chiedere" a se' stesso: `puo()`
risponde no. Il creatore invece puo' tutto, quindi puo' anche chiedere, e la
pagina gli mostrerebbe due moduli - avanza e chiedi - uno dei quali gli
proporrebbe di chiedere il permesso a se' stesso. Quale modulo disegnare lo
decide la rotta (`_contesto_fasi`), con una riga sola: chi puo' avanzare non
chiede. **Non e' una decisione di permesso** ed e' per questo che non sta in
`permissions.py`: il permesso il creatore ce l'ha, e una richiesta costruita a
mano verrebbe accolta.

---

## D-057 — `approved_by_id` diventa `decided_by_id`

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** La colonna di `phase_transitions` che dice chi ha risposto a una
richiesta si chiama `decided_by_id` e non piu' `approved_by_id`. Accanto a lei
ci sono `state` (`richiesta`, `approvata`, `respinta`), `decided_at`,
`decision_reason` e `seen_at`.

**Motivazione.** Una richiesta di passaggio si puo' anche **respingere**, e in
quel caso chi ha deciso va scritto esattamente come quando ha approvato: e' la
riga che fra un anno risponde a "perche' a marzo il progetto e' rimasto fermo".
Una colonna chiamata "approvato da" che contiene il nome di chi ha detto di no
mente a chi la legge, e chi la legge fra due anni non ha modo di accorgersene.

Il rinomino e' stato possibile senza costi perche' la tabella era **vuota su
tutti i database**: esisteva dalla sessione 2 e il flusso che la riempie nasce
adesso.

**Conseguenza.** `decided_at` non e' `created_at`. Una richiesta scritta lunedi'
e approvata giovedi' ha cambiato la fase **giovedi'**, e la durata delle fasi si
misura su quello: misurarla su lunedi' direbbe che il progetto e' stato in due
fasi contemporaneamente per tre giorni.

---

## D-058 — Un progetto chiuso e' in sola lettura, tranne che per il creatore

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** Quando un progetto entra nella fase che lo chiude, `closed_at`
viene valorizzato e da quel momento tutto quello che c'e' dentro smette di
cambiare: niente documenti nuovi, niente cambi di stato dei documenti, niente
passaggi di fase, niente richieste. Resta **visibile** a chi lo vedeva prima.
Il creatore continua a poter tutto, ed e' l'unico che possa **riaprirlo**,
riportandolo a una fase precedente.

**Motivazione.** Un progetto chiuso e' un archivio, e un archivio si consulta:
nasconderlo perderebbe la parte utile. Ma un archivio a cui si continua ad
aggiungere non e' piu' la fotografia di com'e' finito il lavoro, ed e' proprio
quella fotografia che serve quando il cliente telefona due anni dopo.

La regola sta in `permissions.py` e in nessun altro posto - dentro
`_permessi_su_classificazione` per i documenti, dentro `_puo_sul_progetto` per
il progetto, piu' la sua copia SQL in `filtro_documenti` - perche' le strade che
portano a caricare un documento sono tre, e una regola messa su due di quelle
tre e' una regola che non c'e' (D-051).

**Conseguenza.** Il messaggio del 403 e' a parte e non dipende dal ruolo di chi
chiede: "questo progetto e' chiuso" e' vero per tutti allo stesso modo,
responsabile compreso, e dirgli "il tuo ruolo non permette" lo manderebbe a
cercare un permesso che non esiste.

**Il ritorno a una fase precedente riapre il progetto**, azzerando `closed_at`.
E' il caso raro ma reale della chiusura sbagliata: se il ritorno e' consentito -
e da una fase che blocca non lo e' - allora il progetto sta ricominciando a
muoversi, e lasciarlo segnato come chiuso sarebbe una contraddizione scritta in
due colonne.

---

## D-059 — Le fasi non sono un terzo grafo di transizioni

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** Il flusso delle fasi sta in `app/services/phases.py` e non in
`app/services/lifecycle.py`, dove CLAUDE.md dice che stanno **tutti** i grafi
delle transizioni.

**Motivazione.** Non e' un'eccezione alla regola: e' che le fasi non sono un
grafo. Gli stati di un ciclo di vita sono un elenco chiuso scritto in
`enums.py`, con delle frecce decise dal programma e scritte in una tabella
Python; le fasi sono **righe di una tabella del database**, in un ordine che
stabilisce chi crea il modello. In `phases.py` non c'e' nessun elenco di
transizioni ammesse: c'e' "la successiva e' quella con `sort_order` piu' alto",
che e' una lettura, non una regola.

Un grafo di fasi scritto in Python sarebbe esattamente l'errore che la
sessione 8 doveva evitare (D-055).

**Conseguenza.** La regola di CLAUDE.md resta com'e': i grafi sono due e stanno
tutti e due in `lifecycle.py`. Una nota in cima a `phases.py` spiega perche'
quel file non ne e' il terzo, cosi' chi legge la regola e poi trova questo file
non deve chiederselo.

---

## D-060 — La notifica dell'esito e' una colonna, non una tabella

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** Chi ha chiesto un passaggio di fase viene informato dell'esito
con un avviso sul proprio cruscotto, che sparisce quando lo chiude. Il "l'ho
letto" e' la colonna `phase_transitions.seen_at`. Non c'e' nessuna tabella
`notifications`.

**Motivazione.** La tabella delle notifiche e' lavoro della sessione 10, che le
progettera' insieme alla posta e ai modelli dei messaggi. Inventarla adesso per
un caso solo vorrebbe dire progettarla senza sapere che cosa dovra' contenere, e
la sessione 10 si troverebbe fra le mani una tabella da correggere invece che da
scrivere - che e' il modo in cui i progetti si impantanano (CLAUDE.md, sezione
7, regola 2).

**Conseguenza.** Quando la tabella delle notifiche arrivera', `seen_at`
diventera' una sua riga e questa colonna sparira' con la sua migrazione. Fino ad
allora la notifica funziona, e questo era quello che la sessione chiedeva ("in
questa sessione basta una notifica dentro l'applicazione").

Il "l'ho letto" **non finisce nell'audit trail**: aver chiuso un avviso non e'
un'operazione sui dati dell'azienda, e una riga di registro per ogni notifica
letta renderebbe illeggibile il registro delle cose che contano.

---

## D-061 — Le milestone si innestano sulle fasi, e non toccano il flusso (R2)

**Data:** 26 agosto 2026 · **Stato:** attiva, ma non realizzata

**Decisione.** Le milestone sono del rilascio R2 e la sessione 8 **non le
realizza**. Il modello dati e l'interfaccia sono pero' stati lasciati nella
forma che permette di aggiungerle senza rifare niente di quello che c'e'.
Questa voce dice come, perche' fra sei mesi la domanda sara' "dove le attacco?".

**Dove si attaccano.** Una tabella nuova, `milestones`, con una riga per
milestone di un **modello di fasi**:

| Colonna | Note |
|---|---|
| `phase_id` | `NN` -> `phases.id`. La milestone appartiene a una fase, non al modello: e' una cosa che va fatta *dentro* quella fase. |
| `name`, `description` | come per le fasi |
| `sort_order` | l'ordine dentro la fase |
| `is_required` | se il passaggio alla fase successiva la pretende |

E una seconda, `project_milestones`, con una riga per (progetto, milestone): chi
l'ha completata, quando, con quale nota. E' lo stesso schema di
`phases`/`phase_transitions`: il modello descrive il percorso, l'altra tabella
racconta che cosa e' successo su un progetto.

**Perche' il flusso non cambia.** L'unico punto che le milestone toccano e'
`phases.avanza()`, che oggi ha una condizione sola ("c'e' una fase
successiva?") e ne avra' due ("...e le milestone obbligatorie di questa fase
sono tutte completate?"). Il rifiuto e' gia' previsto: si solleva
`PassaggioNonAmmesso` con il messaggio giusto, come fa oggi il divieto di
tornare indietro, e la pagina lo mostra senza sapere che cosa sia una
milestone. La richiesta, l'approvazione, il rifiuto, lo storico e la chiusura
non cambiano di una riga.

**Perche' l'interfaccia non cambia.** La barra dell'avanzamento
(`components/avanzamento.html`) prende un elenco di dizionari e disegna quello
che c'e' dentro: le milestone di una fase diventano una riga in piu' sotto il
pallino, oppure il contatore "3 su 5" accanto al nome, senza toccare il
componente. La griglia delle fasi del modello (`components/griglia_fasi.html`)
ha gia' due spunte per riga: le milestone saranno una colonna in piu' della
stessa griglia, o una pagina figlia della scheda del modello.

**Quello che gia' oggi le rende possibili.** I modelli di fasi sono immutabili e
versionati (D-016): le milestone nascono dentro una versione del modello e i
progetti gia' avviati non le vedono comparire a meta' strada. Se i modelli si
potessero correggere, aggiungere una milestone obbligatoria bloccherebbe di
colpo dei progetti in corso, ed e' esattamente il genere di sorpresa che questo
progetto evita.

---

## D-062 — Ogni voce del registro porta con se' la sua frase in italiano

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** `audit_logs` ha una colonna `description`, di testo, obbligatoria.
La frase la compone `audit.record()` **al momento in cui il fatto avviene** e
non si ricalcola mai piu'.

**L'alternativa scartata** era comporre la frase quando si disegna la pagina,
a partire da `action`, `entity_type` e i due valori JSON. Costa una colonna in
meno e ha due difetti che non si possono aggirare.

Il primo: se domani un documento cambia titolo, la riga del registro di sei
mesi fa comincerebbe a raccontare il fatto con il nome nuovo. Un registro deve
dire com'erano le cose **quel giorno**, e "Documento caricato: Schema
elettrico" resta vero anche dopo che quel documento e' stato ribattezzato
"Schema del convertitore".

Il secondo: la frase entra nell'impronta della voce (D-063). Una frase
ricalcolata a ogni lettura non si puo' firmare.

**Come si compone.** Tre pezzi, e gli ultimi due sono facoltativi:
l'etichetta italiana dell'azione, presa dal catalogo; il nome con cui una
persona chiama l'oggetto, passato da chi chiama `record()`; i campi cambiati
con il valore di prima e quello di dopo, ricavati da `old_value` e `new_value`.

    Stato del documento cambiato: Schema elettrico (state: bozza -> rilasciato)

**Il catalogo delle azioni** (`audit.CATALOGO`) e' la seconda meta' della
decisione: ogni azione registrabile ha li' la sua frase e il suo gruppo.
Prima le costanti `ACTION_*` erano sparse nei servizi che le usavano, e alla
domanda "quali operazioni vengono registrate?" si poteva rispondere solo
leggendo tutto il programma. C'e' un test che legge i sorgenti e diventa rosso
se qualcuno aggiunge un'azione senza catalogarla.

**Il nome dell'oggetto lo passa chi chiama.** `record()` non interroga il
database per andarsi a cercare il titolo di un documento: una funzione che
scrive nel registro non deve rallentare ogni operazione del programma. Le
funzioni che compongono i nomi stanno in `app/services/etichette.py`, che
importa solo i modelli e quindi lo puo' importare chiunque senza creare
importazioni circolari.

---

## D-063 — Il registro e' incatenato: ogni voce porta l'impronta della precedente

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** Ogni riga di `audit_logs` contiene l'impronta SHA-256 della riga
precedente (`previous_hash`) e la propria (`entry_hash`), calcolata su tutti i
campi che raccontano il fatto piu' il numero di sequenza e l'impronta
precedente. `scripts/verifica_audit.py` ricalcola la catena e segnala che cosa
non torna.

**Che problema risolve.** I permessi del database (D-064) impediscono ad Aurora
di modificare il registro. Non impediscono niente a chi amministra il database:
con le credenziali di `postgres` si corregge qualunque riga. Contro quello non
esiste difesa **dentro** il database, e fingere il contrario sarebbe peggio che
non fare niente.

Quello che si puo' fare e' rendere la manomissione **visibile**. Cambiando una
riga cambia la sua impronta, e da li' in avanti nessuna delle successive torna
piu'. Per non farsi scoprire bisognerebbe rifare le impronte di tutte le voci
seguenti - cosa possibile, ma non piu' un `UPDATE` distratto - e comunque non
tornerebbero i confronti con le esportazioni CSV gia' uscite da Aurora, che le
impronte se le portano dietro.

**Perche' serve un numero di sequenza e non basta `occurred_at`.** La catena ha
bisogno di un ordine **totale e certo**. Due operazioni scritte nello stesso
centesimo di secondo hanno la stessa ora, e la catena non saprebbe quale delle
due viene prima. `seq` e' un intero con vincolo di unicita': l'ordine c'e'
sempre, e un buco nella numerazione e' esso stesso un'anomalia da segnalare.

**Perche' un lucchetto e non una sequenza del database.** Il numero e
l'impronta si decidono insieme, e la seconda dipende dall'impronta della voce
prima: due transazioni che leggessero contemporaneamente l'ultima voce
scriverebbero due righe con lo stesso "precedente" e la catena si
biforcherebbe. Al momento del flush si prende `pg_advisory_xact_lock`, che si
rilascia da solo alla fine della transazione. Costa la serializzazione delle
sole scritture del registro: per qualche decina di utenti in rete locale non si
vede. Il vincolo di unicita' su `seq` e' li' a dimostrare che non stiamo
indovinando.

**Perche' al flush e non dentro `record()`.** Fra la chiamata a `record()` e il
momento in cui la riga arriva davvero al database possono passare altre
operazioni, e la catena deve rispecchiare l'ordine in cui le righe vengono
**scritte**. Il flush e' l'unico momento in cui quell'ordine e' deciso.
Effetto collaterale voluto: una riga di `audit_logs` aggiunta senza passare da
`record()` non arriva al listener, resta senza `seq` e l'INSERT fallisce sul
vincolo `NOT NULL`. E' il database che fa rispettare D-018.

**Il JSON va normalizzato.** `jsonb` non conserva l'ordine delle chiavi:
rileggendo la riga, PostgreSQL puo' restituirle in un ordine diverso da quello
in cui sono state scritte. Senza `json.dumps(..., sort_keys=True)` la verifica
direbbe "manomesso" su un registro intatto. Stessa cosa per le date, riportate
sempre a UTC prima di entrare nell'impronta. C'e' un test che rilegge una voce
dal database e ne ricalcola l'impronta.

---

## D-064 — La non modificabilita' del registro la fa rispettare il database

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** L'utente PostgreSQL con cui Aurora si collega ha su `audit_logs`
i permessi `SELECT` e `INSERT`, e **non** ha `UPDATE`, `DELETE` ne' `TRUNCATE`.
La procedura sta in `scripts/hardening_db.sql`, spiegata in
`scripts/hardening_db.md`.

**Perche' non basta il programma.** In `app/services/audit.py` c'e' una sola
funzione che scrive nel registro e non ce n'e' nessuna che lo corregge. E' vero
oggi. Potrebbe non esserlo fra due anni: basta che qualcuno aggiunga una
funzione "per sistemare una riga sbagliata". Un permesso che fa rispettare il
database non si dimentica, e chi verifica Aurora non deve fidarsi della parola
di chi l'ha scritta: apre `psql` e guarda.

**Tre cose che ne discendono, e sono tutte e tre prezzi da pagare
consapevolmente.**

1. **La tabella non appartiene piu' all'utente applicativo.** Un proprietario
   puo' sempre ridarsi i permessi che si e' tolto: finche' `audit_logs`
   appartiene ad `aurora_app`, il divieto e' una porta chiusa con la chiave
   nella toppa. La proprieta' passa ad `aurora_owner`, un ruolo senza
   `LOGIN` che non serve a lavorare.

2. **Le migrazioni che toccano `audit_logs` vanno eseguite come `postgres`.**
   Un `ALTER TABLE` e' un'operazione da proprietario. E' scritto in
   `scripts/hardening_db.md`, ed e' il motivo per cui l'irrobustimento si
   applica **dopo** `alembic upgrade head` e non prima: la migrazione
   `e2f5a91c73d8` e' l'ultimo `UPDATE` che verra' mai eseguito su quella
   tabella.

3. **Il test che lo verifica non si salta.** `tests/test_registro.py` prova a
   fare un `UPDATE` e pretende che fallisca. Gli altri test che dipendono
   dall'ambiente si saltano (conftest.py lo fa per le migrazioni mancanti);
   questo no, e la differenza e' che senza migrazioni Aurora non funziona
   affatto - la mancanza si vede subito - mentre senza questi permessi
   funziona benissimo, e la mancanza si vede il giorno della verifica
   aziendale.

**In piu', e non al posto:** due trigger rifiutano `UPDATE`, `DELETE` e
`TRUNCATE` chiunque li faccia, superutente compreso. Non fermano chi vuole
davvero manomettere il registro - un superutente li disattiva - ma fermano lo
sbaglio, che e' il rischio vero: l'`UPDATE` senza `WHERE` scritto in `psql`
alle otto di sera.

---

## D-065 — Le voci del registro non si cancellano: si archiviano, e la copia resta

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** La politica di conservazione del registro e' "per sempre".
`scripts/archivia_audit.py` scrive un file `.csv.gz` con le voci piu' vecchie
di N anni e **non cancella niente dal database**. Non e' agganciato a nessun
lavoro pianificato e non va agganciato senza pensarci.

**Perche' non si cancella.** E' la regola 5 di CLAUDE.md applicata alla tabella
a cui si applica peggio. Un registro con dentro un buco, in sede di verifica,
non vale come un registro con dentro tutto: vale come un registro assente,
perche' nessuno puo' dimostrare che il buco fosse innocente. E con la catena di
impronte (D-063) un buco e' anche letteralmente un'anomalia, che
`verifica_audit.py` segnalerebbe per sempre.

**A che serve allora l'archivio.** A due cose che con il database non si fanno:
consegnare il registro a chi verifica senza dargli accesso al programma, e
tenerne una copia fuori dal database, dove un ripristino sbagliato non la puo'
toccare. Il file contiene le impronte di ogni voce, quindi si verifica anche a
distanza di anni.

**Perche' non si esegue da solo.** Un lavoro notturno che scrive file da
qualche parte e nessuno guarda dove finiscono e' il modo in cui una copia del
registro esce dall'azienda senza che nessuno l'abbia decisa. Questo script lo
lancia una persona che sa perche' lo sta facendo. E lo lascia scritto nel
registro: l'archiviazione e' registrata come tutto il resto (`audit.archived`),
esattamente come l'esportazione dalla pagina.

**Se un giorno il database diventasse davvero ingestibile** - non e' il caso di
un'azienda con qualche decina di persone e qualche migliaio di righe l'anno -
la risposta sara' una tabella storica, non un `DELETE`. E la decisione andra'
presa da chi risponde dei dati, non da uno script.

---

## D-066 — Il CSV del registro esce con il punto e virgola e il BOM

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** I file CSV che Aurora produce - l'esportazione dalla pagina
`/registro` e l'archivio compresso - usano il **punto e virgola** come
separatore e cominciano con il **BOM** UTF-8.

**Perche'.** Quei file li apre una persona, con Excel, su un Windows in
italiano. Con la virgola, Excel in italiano mette tutta la riga in una cella
sola; senza BOM, legge un file UTF-8 come se fosse a codifica di sistema e le
lettere accentate diventano geroglifici. Sono due difetti che si vedono subito
e fanno perdere mezz'ora a chi non sa perche' succede.

Il prezzo e' che il file non e' un CSV "puro" secondo l'RFC 4180. E' un prezzo
accettabile: nessuno legge questi file con un programma, e chi lo facesse
saprebbe indicare il separatore. Il senso di questa esportazione e' che qualcuno
possa aprirla e leggerla, non che un altro programma la digerisca.

**Le impronte sono nel file**, due colonne in fondo. Un'esportazione che le
omettesse sarebbe una copia del registro che non si puo' piu' verificare, e chi
la riceve dovrebbe fidarsi sulla parola.

---

## D-067 — La storia di un oggetto e' una pagina a se', e la vede chi vede l'oggetto

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** Ogni oggetto di Aurora - prodotto, versione, progetto,
documento, persona - ha una linguetta **Storico** che porta a
`/<sezione>/{id}/storico`. E' una **pagina diversa**, non una scheda che si
apre dentro quella dell'oggetto.

**Perche' una pagina e non una scheda nella stessa pagina.** Il componente
`components/schede.html` offre tutti e due i modi e dice quando si usa
ciascuno: le schede nella stessa pagina mandano al browser tutto il contenuto
insieme, e vanno bene per tre riquadri di dettaglio. Lo storico di un oggetto
con anni di vita e' un elenco impaginato che va interrogato: mandarlo insieme
alla scheda vorrebbe dire far aspettare chi voleva soltanto leggere il titolo
di un documento. In piu' cosi' ha un indirizzo suo, che si manda a un collega:
"guarda chi ha scaricato questo documento" e' esattamente il messaggio per cui
serve.

**L'indirizzo sta sotto l'oggetto**, `/progetti/{id}/storico` e non
`/storico/progetti/{id}`, per due motivi: la barra laterale continua a segnare
la sezione giusta (`sezione_corrente()` in `app/navigation.py` guarda il primo
pezzo del percorso), e l'indirizzo dice da solo di che cosa si sta guardando la
storia.

**Chi la vede e' chi vede l'oggetto**, e la domanda la fa sempre
`permissions.puo()` (D-051). Per rispondere, quella funzione ha dovuto imparare
un oggetto in piu', il `Product`. Le persone sono l'eccezione: le loro pagine
stanno tutte nella sezione riservata al creatore, e la rotta dello storico
dichiara `Depends(richiedi_creatore)` come le altre di quella sezione. E' la
stessa domanda fatta nel modo previsto per le pagine di amministrazione, e la
risposta negativa e' un **403** invece del 404 di `pretendi()`: due pagine
vicine che rispondono in due modi diversi alla stessa domanda mandano chi
indaga a cercare un guasto che non c'e'.

**Non e' la stessa cosa di `/registro`.** Li' c'e' tutto il registro e lo vede
il solo creatore, perche' messo insieme dice anche a che ora entra ed esce
ciascuno. Qui c'e' la storia di un oggetto solo: un ingegnere deve poter
rispondere alla domanda "chi ha cambiato lo stato di questo documento venerdi'"
senza chiedere il permesso a nessuno.

**Le voci si cercano per identificatore e non per coppia (tipo,
identificatore).** Gli identificatori sono UUID generati a caso, quindi due
righe di tabelle diverse non possono avere lo stesso: la storia di un progetto
puo' cosi' comprendere le sue assegnazioni e i suoi passaggi di fase, che nel
registro sono voci con un `entity_type` diverso. Senza, la meta' piu'
interessante della storia di un progetto - chi e' entrato nella squadra, chi ha
chiesto un avanzamento e chi l'ha respinto - non comparirebbe.

---

## D-068 — Le modifiche alla configurazione si registrano confrontando gli avvii

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** Aurora registra il **fatto** che la configurazione con cui sta
girando sia diversa da quella dell'avvio precedente (`config.changed`), con il
valore di prima e quello di adesso dei soli parametri cambiati. Non registra
chi ha modificato il file, perche' non lo sa.

**Il problema.** La regola 8 di CLAUDE.md dice che la configurazione sta nel
file `.env` e nei file di `config/`, e si cambia sul server con un editore di
testo. Non c'e' nessuna pagina che la modifichi, quindi non c'e' nessuna
operazione dell'utente da registrare - e "le modifiche alla configurazione"
resterebbero l'unica cosa importante che succede ad Aurora e di cui il registro
non sa niente.

**Perche' e' comunque utile.** Chi verifica il programma fra un anno, davanti a
un documento scaricato da un indirizzo che non si aspettava, deve poter sapere
se quel giorno Aurora era collegata al database di produzione o a quello di
collaudo, quale regola di scomposizione dei codici era in uso, quanto durava
una sessione. Il registro adesso lo dice.

**Chi ha cambiato il file lo dicono i permessi del filesystem e il registro di
Windows**, non Aurora. Scriverci il nome di chi ha riavviato il server sarebbe
la peggiore delle bugie da mettere in un audit trail: l'utente della voce e'
nullo, cioe' "sistema".

**I segreti non entrano.** Della stringa di connessione si registra tutto
tranne la password - indirizzo, porta, database e utente restano leggibili, e
devono - e della chiave di firma dei cookie si registra l'impronta accorciata,
che dice se e' cambiata senza dire qual e'. Dei file di `config/` si registra
l'impronta e non il contenuto: sono tabelle intere, e quello che serve sapere
e' se sono cambiate.

**Una sola eccezione alla regola di `record()`.** In `new_value` finisce la
configurazione **intera** e non i soli campi cambiati, perche' quella voce fa
anche da fotografia per il confronto dell'avvio successivo. In `old_value`
finiscono invece i soli valori di prima dei parametri cambiati, che e' quello
che serve leggere. La descrizione la compone la funzione a mano, altrimenti
elencherebbe tutti e diciassette i parametri invece dei due che contano.

**Un riavvio che non cambia niente non scrive niente.** Un registro con dentro
una riga a ogni riavvio del server e' un registro in cui non si trova piu'
nulla.

---

## D-069 — La posta e' una classificazione, non un sistema di permessi a parte

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** Un messaggio di posta si vede con la **stessa identica regola**
di un documento: e' trattato come un documento di classificazione
**"Corrispondenza"** nel progetto aperto sulla versione di prodotto a cui e'
attaccato. `permissions.puo()` ha imparato un oggetto in piu' - `EmailMessage`
- e la sua risposta la calcola `_permessi_su_classificazione()`, che e' la
stessa funzione dei documenti. La riga di `classifications` la crea la
migrazione `d4b8607e15a2` con le sue tre caselle della matrice.

**Il problema.** La sessione 10 porta dentro Aurora un genere di contenuto
nuovo, e la corrispondenza con i clienti e' riservata quanto i documenti: ci
sono dentro i prezzi, le deroghe concordate, i nomi delle persone. Serviva una
regola di accesso, e la tentazione era scriverne una nuova - "la posta la vede
chi e' nella squadra" - perche' i messaggi non hanno una colonna
`classification_id` come i documenti.

**Perche' invece si riusa la matrice.** Una seconda regola di accesso e' una
regola che si disallinea. D-051 dice che i permessi si decidono in un punto
solo, e il motivo e' che le regole di accesso sbagliate non si vedono: un
elenco che mostra una riga di troppo sembra un elenco normale. Se la posta
avesse la sua regola, il giorno in cui si corregge la matrice per i documenti
la posta resterebbe indietro, e nessuno se ne accorgerebbe.

Con questa scelta invece la matrice ha una colonna in piu' che si amministra
dalla pagina di sempre, chi ha gia' capito come funzionano i permessi dei
documenti non deve imparare niente di nuovo, e la verifica degli accessi di una
persona (`/permessi/verifica`) comprende la posta senza una riga di programma.

**La classificazione si cerca per nome.** E' l'unico modo di riferirsi a una
riga che una persona puo' rinominare dalla pagina delle classificazioni. Se
manca, tutte le domande sulla posta rispondono "no" tranne che per il creatore,
e il guasto finisce nel registro su file: e' l'unico modo prudente di
sbagliare, perche' senza la riga non esiste nessuna casella da guardare.

**La quarantena e' l'eccezione, ed e' riservata al creatore.** Un messaggio non
attribuito non e' attaccato a nessuna versione, quindi non c'e' nessun progetto
su cui la matrice possa dire qualcosa: nessun ruolo, nessuna casella, nessun
permesso decidibile. L'unica regola scrivibile e' "lo vede chi amministra
Aurora", e la pagina `/posta/quarantena` dichiara `Depends(richiedi_creatore)`
come tutte le altre pagine riservate. Vale lo stesso per un messaggio
attaccato a una versione su cui non e' ancora stato aperto nessun progetto:
capita per la posta che arriva prima che il lavoro cominci.

**Le tre caselle di partenza** sono nella migrazione e in `scripts/seed.py`: il
project manager puo' tutto, l'ingegnere legge e puo' **correggere
l'attribuzione** di un messaggio finito sulla versione sbagliata - e' lui che
se ne accorge - il lettore legge e basta. La casella "caricare" non ha senso
per la posta (i messaggi arrivano dalla casella, non si caricano a mano) ma
esiste lo stesso, perche' una casella che manca a distanza di mesi non si
distingue da una dimenticanza.

---

## D-070 — Ogni messaggio ha la sua transazione, e la chiude il servizio

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** `emails.elabora_messaggio()` finisce con un `commit()` suo, ed
e' **l'unico punto di Aurora in cui un servizio decide quando scrivere** invece
di lasciarlo alla rotta che lo ha chiamato. Un errore su un messaggio produce
un `rollback()` e un esito di errore; il giro prosegue con i messaggi
successivi.

**Il problema.** La regola generale di Aurora e' che i servizi aggiungono righe
alla sessione e il commit lo fa la rotta, insieme all'operazione che le righe
descrivono: cosi' o si scrive tutto o non si scrive niente. Per l'acquisizione
della posta quella regola dice la cosa sbagliata. Il punto 6 della sessione
chiede che l'elaborazione di un messaggio sia una transazione - "se qualcosa
fallisce a metà, non deve restare nulla di parziale" - e il punto 7 chiede che
un errore su un messaggio non interrompa gli altri. Con una transazione unica
per tutto il giro le due richieste si contraddicono: il cinquecentunesimo
messaggio storto porterebbe con se' i cinquecento gia' archiviati.

**Che cosa resta fuori dalla transazione, e va bene.** Il file `.eml` e gli
allegati vanno nell'archivio **prima** di qualunque riga, come fa gia'
`documents.deposita_file()`. Se poi la scrittura fallisce, nell'archivio resta
un oggetto che non riferisce nessuno: non e' un problema - non si cancella
(regola 5 di CLAUDE.md), non occupa quasi niente, e al tentativo successivo la
deduplicazione lo riusa.

**Lo spostamento del file avviene dopo il commit.** Se il programma si spegne in
mezzo, il file resta nella cartella e al giro successivo viene riletto,
riconosciuto come gia' archiviato dal suo `Message-ID` e spostato allora: la
cartella si svuota comunque e nel database non compare niente due volte.
L'ordine inverso - sposta e poi scrivi - perderebbe il messaggio per sempre.

**Un errore lascia il file dov'e'.** E' l'unico modo perche' il giro successivo
lo riprovi, ed e' anche il motivo per cui il caso del carattere nullo (vedi
sotto) andava risolto e non ignorato: un file che fallisce sempre resterebbe li'
a fallire per sempre.

---

## D-071 — I motivi della posta sono una tabella, non un file di configurazione

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** L'elenco dei motivi ammessi nella terza parentesi dell'oggetto
(`[RMS1100-24-110SW][V2][SPECS]`) sta nella tabella `email_reasons` e si
amministra dalla pagina `/posta/motivi`, riservata al creatore. Non e' un file
in `config/` come la scomposizione dei codici prodotto e l'elenco dei tipi di
documento.

**Perche' non un file.** I due file di `config/` esistono per una ragione
precisa (D-038): sono regole che l'azienda potrebbe cambiare, e cambiarle non
deve costare una modifica al programma. Ma chi li cambia e' chi amministra la
**macchina**, con un editore di testo e un riavvio del server. Questo elenco
invece lo cambia chi usa Aurora, dal browser, mentre il server e' in funzione;
e ogni cambiamento deve lasciare una riga nel registro delle operazioni. Sono
esattamente le due cose che un file di testo non sa fare. Il punto 8 della
sessione chiede "configurabile dall'interfaccia", e l'interfaccia scrive nel
database.

**Il motivo non decide niente**, ed e' il motivo per cui questa tabella e'
piccola e innocua. Un oggetto con una sigla che non e' in elenco viene
attribuito lo stesso: quello che conta e' il codice prodotto. La sigla
sconosciuta resta scritta in `subject_parsed` con `motivo_riconosciuto: false`,
cosi' chi amministra si accorge che ne serve uno nuovo. Rifiutare
l'attribuzione per una sigla fuori elenco vorrebbe dire mettere in quarantena
della posta che sappiamo benissimo a chi appartiene.

**Il codice di un motivo si puo' correggere**, a differenza del nome utente:
qui non c'e' niente che ci punti. I messaggi gia' archiviati portano il motivo
scritto dentro `subject_parsed`, che e' una copia del giorno in cui il
messaggio e' arrivato e non un collegamento a questa riga.

---

## D-072 — La versione a cui attaccare un messaggio, quando l'oggetto non la dice

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** Un messaggio il cui oggetto nomina il prodotto ma non la
versione va alla **versione piu' recente non chiusa**, cioe' al numero piu'
alto fra quelle che non sono ne' `superato` ne' `obsoleto`. Quando **tutte** le
versioni sono chiuse si prende comunque la piu' recente.

**Il problema.** Il punto 5a della sessione dice "se la versione non è
indicata, usa la versione più recente non chiusa di quel prodotto", e non dice
che cosa fare quando di versioni non chiuse non ce n'e' nessuna. Non e' un caso
di laboratorio: succede a ogni prodotto che esce di produzione, ed e' proprio
allora che arrivano le contestazioni e le richieste di ricambi.

**Perche' non la quarantena.** In quel caso il prodotto lo conosciamo con
certezza - il suo codice sta scritto nell'oggetto - e la quarantena e' la
domanda che si fa a una persona quando **non** si sa. Mandarci un messaggio di
cui si sa tutto vorrebbe dire far smistare a mano tutta la corrispondenza dei
prodotti fuori produzione, che e' il modo piu' sicuro di far smettere di usare
la quarantena per quello a cui serve.

**Che cosa vuol dire "chiusa" e dove sta scritto.** Sono i due stati
`superato` e `obsoleto`, elencati in `emails.STATI_CHIUSI`. Stanno li' e non in
`lifecycle.py` perche' non sono una transizione: `lifecycle.py` e' il file dei
**passaggi** fra stati (CLAUDE.md, sezione 8), e questo e' il modo in cui la
posta legge uno stato.

---

## D-073 — Una versione dichiarata che non esiste manda il messaggio in quarantena

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** Quando l'oggetto di un messaggio dichiara una versione precisa -
`[RMS1100-24-110SW][V7]` - e quella versione non esiste, il messaggio va in
quarantena **senza provare le regole successive**, con scritto il perche'.
Aurora non ne sceglie un'altra al posto del mittente.

**Il problema.** Le quattro regole di attribuzione si provano in ordine e la
seconda cerca il codice prodotto **ovunque** nell'oggetto, parentesi comprese.
Senza questa decisione, `[RMS1100-24-110SW][V7]` su un prodotto che di versioni
ne ha due fallirebbe la prima regola, passerebbe la seconda - il codice c'e' -
e il messaggio finirebbe sulla versione piu' recente, cioe' su una **diversa**
da quella che il mittente ha scritto.

**Perche' si preferisce chiedere.** Meta' delle decisioni tecniche di un
progetto sta nelle mail: una modifica concordata al telefono e confermata per
iscritto, un nulla osta, una deroga. Una decisione archiviata sotto la versione
sbagliata e' una decisione persa, e non se ne accorge nessuno - il messaggio
c'e', e' solo nel posto sbagliato. La quarantena non e' un errore e non e' un
blocco: e' una riga in una coda di lavoro, con accanto la frase che dice che
cosa e' successo ("L'oggetto chiede la versione 99 del prodotto X, che non
esiste") e il pulsante per assegnarlo.

**Non e' in contrasto con "mai scartare, mai bloccarsi".** Il messaggio viene
archiviato per intero, file originale e allegati compresi, e resta consultabile:
manca solo l'attribuzione, che e' esattamente quello che la quarantena esiste
per raccogliere.

---

## D-074 — I messaggi senza Message-ID ne ricevono uno ricavato dall'impronta

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** Un messaggio che non dichiara nessuna intestazione `Message-ID`
- capita con i file esportati male e con i file rovinati - viene archiviato con
un identificativo costruito dall'impronta SHA-256 del file:
`aurora-<impronta>@impronta.aurora.local`.

**Il problema.** `email_messages.internet_message_id` e' obbligatorio e unico,
ed e' quello che rende ripetibile tutta l'acquisizione: prima di scrivere
qualunque cosa si chiede se quel messaggio c'e' gia'. Un messaggio senza
identificativo non potrebbe essere archiviato affatto - e la regola della
sessione e' "mai scartare" - oppure ne riceverebbe uno casuale, e allora
verrebbe archiviato di nuovo a ogni rilettura.

**Perche' l'impronta.** E' **stabile**: rileggere lo stesso file produce lo
stesso identificativo, quindi la ripetibilita' vale anche per i messaggi rotti,
che sono proprio quelli che si riprova a leggere piu' spesso. Due file diversi
con lo stesso contenuto sono lo stesso messaggio, ed e' giusto che lo siano: e'
la stessa mail esportata due volte.

**Il dominio inventato e' voluto.** `impronta.aurora.local` non esiste e non
deve esistere: guardando il database si vede subito quali identificativi se li
e' inventati Aurora. Lo dice anche `subject_parsed.identificativo_costruito`.

---

## D-075 — Il carattere nullo non arriva mai al database

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** Tutto il testo estratto da un messaggio - oggetto, corpo,
mittente, indirizzi, nomi degli allegati - passa da
`email_parsing.scrivibile()`, che toglie il carattere nullo (`\x00`). Solo
quello: gli altri caratteri di controllo PostgreSQL li accetta, e toglierli
vorrebbe dire rovinare i messaggi che li contengono per una ragione loro.

**Il problema, scoperto da un test.** PostgreSQL rifiuta il byte zero dentro una
colonna di testo. Un `.eml` rovinato ne contiene a decine - un PDF rinominato,
un file troncato a meta' di un allegato binario - e finiscono dritti nel corpo
del messaggio. Senza la ripulitura l'`INSERT` falliva, il messaggio veniva
contato fra gli errori invece che finire in quarantena, e **il file restava
nella cartella per essere riprovato al giro dopo e fallire di nuovo**: un file
rotto sarebbe comparso fra gli errori per sempre.

**Perche' e' una decisione e non una correzione.** Il caso e' esattamente il
quarto criterio di accettazione della sessione ("un file .eml malformato finisce
in quarantena senza fermare gli altri"), ed e' venuto fuori scrivendo il test
che lo verifica. Vale la pena che resti scritto: la prossima colonna di testo
che raccogliera' contenuto arrivato da fuori avra' lo stesso problema, e il
posto in cui si risolve e' il confine - dove i byte diventano testo - non la
riga dell'`INSERT`.

---

## D-076 — L'interfaccia della fonte di posta nasce prima della seconda fonte

**Data:** 26 agosto 2026 · **Stato:** attiva

**Decisione.** Il motore di acquisizione parla con una `FonteEmail`
(`app/services/mail_source.py`), un'interfaccia di quattro metodi:
`elenca_nuovi_messaggi()`, `scarica_messaggio_grezzo(id)`, `marca_elaborato(id)`,
`sposta_in_quarantena(id)`. La sessione 10 ne realizza **una sola**,
`FonteLocale`, che legge file `.eml` da una cartella. Il collegamento a
Microsoft Graph arriva con la sessione 11.

**Perche' l'interfaccia prima dell'implementazione.** Non e' astrazione
preventiva: e' quello che permette di collaudare il motore **adesso**, senza
nessun accesso alla casella aziendale. I venti casi difficili - l'oggetto con
`R:` davanti, il messaggio senza codice, il filo di conversazione, il file rotto
- si scrivono come file e si rileggono all'infinito. Con Outlook di mezzo,
ciascuno di quei casi sarebbe una mail da farsi mandare da qualcuno.

E' anche la sola forma in cui il collaudo resta possibile per sempre: fra un
anno, chi tocchera' l'attribuzione potra' rieseguire gli stessi venti file
(`scripts/genera_email_prova.py`) e sapere se ha rotto qualcosa.

**E' un `Protocol`, non una classe base astratta.** Non c'e' niente da
ereditare: sono quattro firme, e chi le rispetta va bene. Una classe base con
quattro metodi che sollevano `NotImplementedError` direbbe la stessa cosa in
piu' righe e costringerebbe a ereditare da noi anche chi scrivera' l'adattatore
di Graph.

**Quattro operazioni e non una di piu'.** Non c'e' `cancella`, perche' in Aurora
non si cancella niente (regola 5 di CLAUDE.md): un messaggio archiviato viene
**spostato**. Non c'e' `segna_come_letto`, perche' lo stato di lettura appartiene
alla casella di chi la usa, e Aurora non e' il suo programma di posta.

**`MAIL_PROVIDER=graph` si ferma con una spiegazione** invece di far finta di
niente. Una fonte che restituisse un elenco vuoto lascerebbe credere che la
casella sia vuota, che e' il modo peggiore di non funzionare.

---

## D-077 — Di un messaggio si conserva il MIME integrale, non quello che Graph racconta

**Data:** 27 agosto 2026 · **Stato:** attiva

**Decisione.** `FonteGraph` scarica ogni messaggio dall'indirizzo
`/messages/{id}/$value`, che restituisce il messaggio **come e' arrivato alla
casella**: intestazioni originali, corpo in tutte le sue forme, allegati
dentro. Non si usano i campi che Graph offre gia' pronti (`subject`, `body`,
`from`, `attachments`), che pure sarebbero piu' comodi da leggere.

**Il problema.** Con i campi pronti si scriverebbero meno righe: Microsoft ha
gia' scomposto il messaggio, e Aurora dovrebbe solo copiare. Il guaio e' che
quello che copierebbe non e' il messaggio: e' l'interpretazione che ne da'
Microsoft oggi. Le intestazioni `In-Reply-To` e `References` - su cui si regge
il terzo ramo dell'attribuzione (D-076) - nei campi pronti non ci sono tutte;
la codifica dei caratteri e' gia' stata decisa da qualcun altro; e la firma
digitale di un messaggio firmato, se c'e', non sopravvive a una ricomposizione.

**Le due ragioni per cui si e' scelto il MIME.**

1. **La corrispondenza e' un fatto avvenuto, e i fatti si conservano interi.**
   Meta' delle decisioni tecniche di un progetto sta nelle mail: il file che
   Aurora deposita nell'archivio deve essere quello che si potrebbe mostrare a
   un cliente o a un perito, non una versione ricostruita.
2. **E' identico al contenuto di un file `.eml`.** Il motore della sessione 10
   sa gia' leggerlo, `email_parsing.py` non cambia di una riga, e i ventiquattro
   file di prova continuano a esercitare esattamente lo stesso codice che
   esercitano i messaggi veri. Con i campi pronti ci sarebbero due strade di
   lettura, e la seconda si proverebbe solo in produzione.

**Il costo.** Una chiamata in piu' per messaggio (l'elenco da' solo gli
identificativi) e messaggi piu' grossi da scaricare. Su qualche decina di
messaggi al giorno non si misura.

---

## D-078 — Le delta query, con il filtro sulla data come strada di riserva

**Data:** 27 agosto 2026 · **Stato:** attiva

**Decisione.** Per sapere che cosa c'e' di nuovo nella casella, `FonteGraph`
prova prima le **delta query** (`/mailFolders/inbox/messages/delta`), che sono
il modo con cui Microsoft risponde alla domanda "che cosa e' cambiato da quando
ho guardato l'ultima volta". Se la casella le rifiuta per un motivo che non
riguarda i permessi, si passa al **filtro sulla data di ricezione**
(`isRead eq false and receivedDateTime ge <ultimo istante>`), scrivendolo nel
registro.

Le due strade non si scelgono da configurazione. Un parametro in piu' da
decidere sarebbe un parametro che qualcuno mette storto, e il programma sa gia'
riconoscere da solo quale delle due funziona.

**Il segno avanza solo a giro finito.** E' la parte che conta. Finche' c'e'
anche un solo messaggio elencato e non ancora spostato fuori dalla posta in
arrivo, il gettone delta non viene salvato: al controllo successivo Microsoft
riproporra' la stessa finestra, i messaggi gia' archiviati verranno riconosciuti
dal loro `Message-ID` (D-074) e spostati allora, e quello rimasto indietro
verra' riprovato.

Senza questa regola ci sarebbe un buco vero: le delta query restituiscono le
**differenze**, e un messaggio che noi abbiamo elencato ma non siamo riusciti a
elaborare non e' cambiato - quindi non ricomparirebbe mai piu', e resterebbe
nella posta in arrivo non letto per sempre. E' lo stesso ragionamento del file
che resta nella cartella di `FonteLocale`, applicato a una casella.

**Il confronto sulla data e' "maggiore o uguale" e non "maggiore".** Due
messaggi arrivati nello stesso secondo esistono. Rileggerne uno gia' archiviato
non costa niente - viene riconosciuto e saltato - mentre perderne uno per una
disuguaglianza stretta e' un messaggio che l'azienda ha ricevuto e Aurora non
ha.

---

## D-079 — I messaggi elaborati si spostano in due cartelle della casella

**Data:** 27 agosto 2026 · **Stato:** attiva

**Decisione.** Dopo l'archiviazione, il messaggio viene **spostato** in una
cartella della casella: `Elaborate` se e' stato attribuito a una versione di
prodotto, `Quarantena` se aspetta una persona. Le due cartelle le crea Aurora
la prima volta che servono. Dalla casella non si cancella mai niente, e i
messaggi **non vengono segnati come letti**.

    Posta in arrivo   i messaggi che Aurora deve ancora elaborare
    Elaborate         quelli archiviati e attribuiti
    Quarantena        quelli archiviati che aspettano una persona

**Perche' si sposta invece di segnare come letto.** Segnare come letto sarebbe
meno invadente, ma lo stato di lettura appartiene alla casella di chi la usa,
e Aurora non e' il suo programma di posta - e' la stessa ragione per cui
l'interfaccia `FonteEmail` non ha `segna_come_letto` (D-076). Soprattutto:
spostando, la posta in arrivo contiene **sempre e soltanto quello che resta da
fare**. Chi apre Outlook lo vede a colpo d'occhio, senza aprire Aurora; e la
lettura successiva ha poco da leggere anche se il segnalibro e' andato perso.

**Perche' non si cancella.** Regola 5 di CLAUDE.md, e non e' un formalismo:
il giorno in cui l'attribuzione sbagliasse, l'originale nella casella e' la
seconda copia da cui ripartire. La prima e' nell'archivio per impronta.

**Le due cartelle rispecchiano le due sottocartelle di `FonteLocale`.** Chi
passa dalla cartella di collaudo alla casella vera ritrova la stessa
organizzazione, e la spiegazione da dare a chi usa il programma e' una sola.

---

## D-080 — Un controllo della posta per volta, e il blocco sta nel processo

**Data:** 27 agosto 2026 · **Stato:** attiva

**Decisione.** Il controllo periodico (APScheduler, ogni `MAIL_POLL_MINUTES`
minuti) e il pulsante «Controlla adesso» chiamano la **stessa** funzione,
`mail_scheduler.controlla()`, protetta da un `threading.Lock` preso senza
aspettare. Chi arriva mentre un controllo e' in corso non si mette in coda:
riceve una risposta che dice "e' gia' in corso" e se ne va.

**Perche' una funzione sola.** La differenza fra le due strade e' di due cose:
chi risulta l'autore nel registro (una persona, oppure nessuno) e da dove
arriva la sessione del database. Se fossero due funzioni, la seconda
comincerebbe a differire dalla prima al primo pezzetto aggiunto in fretta, e la
lettura pianificata - quella che nessuno guarda mai - sarebbe quella che si
allontana.

**Perche' il blocco e non una coda.** Due acquisizioni sovrapposte proverebbero
a scrivere lo stesso messaggio due volte - `internet_message_id` e' unico,
quindi la seconda fallirebbe - e a spostare due volte lo stesso messaggio nella
casella. Nessuna delle due cose e' un guasto grave, e tutte e due riempiono il
registro di errori che non raccontano niente. Mettersi in coda sarebbe peggio:
chi ha premuto il pulsante resterebbe fermo ad aspettare la fine di un giro che
non ha chiesto lui.

**Perche' il blocco sta nel processo e non nel database.** Aurora gira come un
processo solo su un server solo (CLAUDE.md, sezione 1). Un blocco nel database
sarebbe una tabella in piu' da scrivere, da mantenere e da sbloccare a mano il
giorno in cui il server si spegne mentre lo tiene: macchinario per un problema
che questa installazione non ha. Se un giorno Aurora girasse su piu' processi,
questa decisione va rifatta - ed e' scritta qui perche' si sappia dove
guardare.

**Il controllo periodico non parte con `MAIL_PROVIDER=locale`**: la cartella
dei file `.eml` non si riempie da sola, e chi ce li mette puo' premere
«Controlla adesso» subito dopo invece di aspettare cinque minuti.

---

## D-081 — La configurazione della posta si scrive dall'interfaccia, nel file `.env`

**Data:** 27 agosto 2026 · **Stato:** attiva

**Decisione.** La pagina `/posta/configurazione`, riservata al creatore, scrive
i parametri della casella **nel file `.env`**, passando da
`app/services/env_file.py`. E' la prima pagina di Aurora che modifica la
configurazione. La regola 8 di CLAUDE.md non cambia: la configurazione vive
ancora e soltanto nel `.env`, e li' la va a leggere chi amministra il server.
Cambia chi la scrive.

**Il problema.** I quattro parametri della casella (organizzazione,
applicazione, segreto, indirizzo) arrivano dall'ufficio informatico su un
foglio, e chi li riceve non ha accesso al server per scriverli. L'azienda ha
chiesto esplicitamente che la configurazione si possa completare senza toccare
file di testo.

**Le due alternative scartate.**

- *Una tabella nel database.* Avrebbe voluto dire una migrazione, un secondo
  posto in cui cercare la configurazione, e il segreto dell'applicazione
  scritto in una tabella che si esporta e si copia. Soprattutto: due sorgenti
  di verita' per la stessa domanda, che e' esattamente la forma di guaio che
  D-051 e D-048 hanno gia' evitato altrove.
- *Lasciare tutto al `.env` a mano.* Onesta, e gia' rifiutata dall'azienda.

**Che cosa garantisce la scrittura.** Si riscrive **solo la riga del parametro
cambiato**, al posto in cui gia' stava - i commenti del `.env` sono la sola
documentazione che chi amministra il server abbia sottomano; la scrittura e'
atomica (prima un file accanto, poi la sostituzione), perche' un `.env` troncato
e' un programma che non riparte piu'; e la copia precedente resta accanto come
`.env.precedente`.

**I valori si applicano anche a `settings` in memoria**, cosi' valgono subito
senza riavviare. L'unica eccezione e' il controllo periodico, che si accende
all'avvio: la pagina lo dice.

**Il fatto finisce nel registro** (`mail_config.updated`), con i valori di prima
e di dopo dei soli parametri cambiati. Del segreto si registra che e' cambiato,
non che cosa e' diventato - e' la stessa regola con cui `configuration.py`
tratta la chiave di firma dei cookie (D-068).

**Il pulsante VERIFICA e' su ogni campo, non uno solo in fondo.** Con un
pulsante solo, la risposta a quattro parametri sbagliati e' "non funziona", e
chi la legge non sa da dove cominciare. Microsoft, per fortuna, ci mette del
suo: i codici `AADSTS` dicono esattamente quale delle tre credenziali ha
rifiutato, e `graph_api.SPIEGAZIONI_AAD` li traduce in una frase italiana che
nomina il campo da riguardare.

---

## D-082 — Il segno di lettura della casella e' un file, non una tabella

**Data:** 27 agosto 2026 · **Stato:** attiva

**Decisione.** Il gettone delta e l'ultimo istante elaborato - cioe' il punto a
cui Aurora era arrivata a leggere la casella - stanno in un file JSON
(`MAIL_GRAPH_STATE_PATH`, di partenza `storage/posta_graph.json`), scritto in
modo atomico. Non in una tabella del database.

**Perche'.** Non e' un dato dell'azienda: e' un segnalibro. Non si consulta,
non si esporta, non entra in nessun rapporto, e **perderlo non costa niente**.
Se sparisce, al controllo successivo Aurora rilegge la posta in arrivo da capo
- che contiene solo messaggi non ancora elaborati, perche' quelli elaborati li
ha spostati lei (D-079) - e il `Message-ID` impedisce comunque i doppioni
(D-074). Il segnalibro fa risparmiare lavoro, non garantisce la correttezza:
quella la garantisce l'unicita' dell'identificativo.

Una tabella avrebbe voluto dire una migrazione e una riga di dati operativi in
mezzo ai dati aziendali, per una cosa che si puo' cancellare senza conseguenze.

**Un file illeggibile non ferma niente**: vale come nessun file, con una riga
nel registro. E' la stessa regola dei file di `config/` (D-039).

---

## D-083 — httpx diventa una dipendenza del programma, non solo dei test

**Data:** 27 agosto 2026 · **Stato:** attiva

**Decisione.** Le chiamate a Microsoft Graph si fanno con **httpx**, che in
`requirements.txt` passa dalla sezione dei test a quella del programma. Non si
aggiunge `requests`, che pure entrerebbe comunque come dipendenza di `msal`.

**Motivazione.** Una libreria HTTP sola invece di due: un timeout da capire, un
modo di trattare gli errori, una libreria da aggiornare quando esce una
correzione di sicurezza. httpx c'era gia' - la usa il finto browser con cui
sono scritti tutti i test delle pagine - quindi non e' una dipendenza nuova, e'
una dipendenza che smette di essere solo dei test.

**Il guadagno vero e' nei test.** `httpx.MockTransport` sostituisce la rete
dentro la libreria stessa: la casella finta di `tests/test_posta_graph.py`
risponde come risponderebbe Graph - stessi codici HTTP, stesse intestazioni,
stesso `Retry-After` - senza nessun finto server da avviare e senza nessuna
libreria di simulazione in piu'. La limitazione di frequenza e il gettone
scaduto si provano cosi', e sono due cose che su una casella vera non si
riescono a far capitare quando si vuole.

**msal resta separata e si importa dentro una funzione.** Serve solo con
`MAIL_PROVIDER=graph`, e Aurora deve poter partire - e i suoi test devono poter
girare - su una macchina in cui non e' installata. Con l'import in cima al
file, la sua assenza romperebbe l'avvio del programma intero invece della sola
pagina della posta.

**Quello che msal si porta dietro, e va saputo.** `pip install msal` installa
anche `requests`, `urllib3`, `cryptography`, `PyJWT` e `charset_normalizer`.
Sono cinque librerie in piu' da aggiornare quando esce una correzione di
sicurezza, ed e' il prezzo di non scrivere a mano il flusso di autenticazione
di Microsoft - che vorrebbe dire firmare richieste e trattare certificati, cioe'
esattamente il genere di codice che non si scrive a mano. Nessuna di loro serve
con `MAIL_PROVIDER=locale`: su un'installazione che legge da una cartella si
puo' fare a meno di installarle, e il programma lo dice invece di rompersi.
