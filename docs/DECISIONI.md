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

**Data:** 25 agosto 2026 · **Stato:** attiva

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

Il 404 e il 403 restano distinti: "non esiste" e "esiste ma non e' tuo" sono
due cose diverse. Nascondere la seconda dietro la prima sembra piu' prudente,
ma manda chi ha davvero bisogno di quel progetto a cercare un guasto che non
c'e', invece che a chiedere l'assegnazione.

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

**Data:** 25 agosto 2026 · **Stato:** attiva

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

**La matrice non si modifica dall'interfaccia.** Questa sessione la legge e
basta: la pagina che la corregge e' rimasta in sospeso dalla sessione 3 ed e'
segnata in `docs/STATO.md`. Fino ad allora la matrice e' quella scritta da
`scripts/seed.py`.

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
