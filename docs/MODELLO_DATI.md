# Modello dati — rilascio R1

Ultimo aggiornamento: **24 agosto 2026**, sessione 3 (nessuna tabella
cambiata: aggiornata solo la sezione 7 con i sospesi ora chiusi).

Questo file descrive le diciannove tabelle create dalla migrazione
`897359b06e69_modello_dati_r1.py`. Una tabella per file in `app/models/`, una
classe per tabella.

Come si legge la parte di dettaglio:

| Sigla | Significato |
|---|---|
| `PK` | chiave primaria |
| `NN` | obbligatoria (`NOT NULL`) |
| `UQ` | unica |
| `IX` | indicizzata |
| `->` | chiave esterna, con la tabella a cui punta |

Tutte le tabelle hanno le stesse tre colonne di servizio, che nel dettaglio
non vengono ripetute:

| Colonna | Tipo | Note |
|---|---|---|
| `id` | UUID | `PK`. Generato da Python, non dal database. |
| `created_at` | timestamptz | `NN`. Messo dal database (`now()`). |
| `updated_at` | timestamptz | `NN`. Aggiornato da SQLAlchemy a ogni UPDATE che passa dai modelli. Un UPDATE scritto a mano in `psql` **non** lo aggiorna. |

---

## 1. I cinque principi del modello

Valgono per tutte le tabelle, senza eccezioni. Se una soluzione ne mette in
difficolta' uno, si cambia la soluzione.

1. **La chiave primaria e' un UUID interno e immutabile.** I codici parlanti —
   codice prodotto, codice cliente, nome utente — sono attributi normali, con
   un vincolo di unicita' dove serve, e **non sono mai chiavi esterne**. Un
   codice prima o poi cambia: quando succede si aggiorna una casella di testo,
   non si rincorrono i collegamenti in venti tabelle.

2. **Niente cancellazione fisica.** Nessun `DELETE` su una tabella
   applicativa. Dove serve togliere qualcosa di vista c'e' un `is_active`
   (anagrafiche, che si disattivano) oppure una coppia data + autore
   (`deleted_at` / `deleted_by_id`, `revoked_at` / `revoked_by_id`), che dice
   anche **chi** e **quando**.

3. **Ogni tabella ha `created_at` e `updated_at`**, sempre con il fuso orario.

4. **Gli stati sono tipi enumerati veri di PostgreSQL**, non testo libero. Uno
   stato scritto male viene rifiutato dal database al momento della scrittura,
   non scoperto sei mesi dopo in un elenco filtrato che non torna.

5. **Le chiavi esterne non hanno `ON DELETE`.** Il comportamento predefinito
   di PostgreSQL e' quello giusto: rifiutare la cancellazione di una riga
   ancora riferita. E' la rete di sicurezza del principio 2.

---

## 2. Come le tabelle si tengono insieme

```
users ──<  user_sessions
  │
  └── riferito da quasi tutto (autore, approvatore, chi ha caricato...)

login_attempts        tabella isolata, tiene i tentativi di accesso
audit_logs            punta a tutto, ma senza chiavi esterne (vedi sotto)

customers ──< contacts
    │
    └──< products ──< product_versions ──┐
                             │           └── derived_from_id (su se stessa)
                             │
                             ├──1:1 projects
                             │
                             └──< email_messages ──< email_attachments
                                       │
projects ──< assignments               │ (la posta si attacca alla VERSIONE,
    │                                  │  non al progetto: la corrispondenza
    ├──< documents ──< document_versions  continua dopo la chiusura)
    │        │
    │        └── classification_id ──> classifications
    │
    ├──< phase_transitions ──> phases
    │
    ├── phase_template_id ──> phase_templates ──< phases
    └── current_phase_id  ──> phases

classifications ──< permission_rules      la matrice dei permessi:
                                          (ruolo nel progetto, classificazione)
```

Due legami meritano di essere letti due volte.

**Il progetto sta sulla versione, non sul prodotto.** `projects.product_version_id`
e' unico: una versione ha al massimo un progetto. La versione 2 di un prodotto
e' un lavoro nuovo, con la sua squadra, i suoi documenti e le sue fasi.

**La posta sta sulla versione, non sul progetto.** Un progetto si chiude, la
corrispondenza con il cliente no: continua quando il prodotto e' gia' in
produzione. Attaccare i messaggi al progetto avrebbe voluto dire perderli il
giorno della chiusura.

---

## 3. Le diciannove tabelle, una riga per ciascuna

| # | Tabella | A che cosa serve |
|---|---|---|
| 1 | `users` | Le persone che usano Aurora: nome utente, impronta della password, ruolo globale. Non si cancellano mai, si disattivano. |
| 2 | `user_sessions` | Le sessioni di accesso aperte: del gettone si conserva l'impronta, non il gettone. Si revocano, non si cancellano. |
| 3 | `login_attempts` | Ogni tentativo di entrare, riuscito o fallito, con nome utente scritto e indirizzo IP: serve a bloccare chi insiste. |
| 4 | `customers` | I clienti per cui l'azienda sviluppa prodotti, con la sigla breve che compare dentro i codici. |
| 5 | `contacts` | Le persone di riferimento presso un cliente: chi si scrive e chi si chiama. |
| 6 | `products` | I prodotti, identificati dal codice parlante (`RMS1100-24-110SW`) e dalla sua scomposizione in `code_parts`. |
| 7 | `product_versions` | Le versioni successive di un prodotto (1, 2, 3), il loro stato nel ciclo di vita e la versione da cui eventualmente discendono. |
| 8 | `projects` | Il lavoro aperto su **una** versione di prodotto: responsabile, modello di fasi, fase corrente, norme applicabili. |
| 9 | `assignments` | Chi lavora a quale progetto e con che ruolo. E' la riga che da' i permessi; si revoca, non si cancella. |
| 10 | `classifications` | Le quattro classi di riservatezza dei documenti: Tecnico, Commerciale, Qualità, Amministrativo. |
| 11 | `permission_rules` | La matrice dei permessi: per ogni coppia (ruolo nel progetto, classificazione) dice se si puo' vedere, caricare, modificare. |
| 12 | `documents` | I documenti di un progetto: titolo, tipo, classificazione, stato, presa in carico ed eventuale disattivazione. |
| 13 | `document_versions` | I file veri e propri, una riga per versione caricata, identificati dall'impronta SHA-256 del contenuto. |
| 14 | `phase_templates` | I modelli di percorso a fasi. Sono immutabili: una correzione diventa una versione nuova. |
| 15 | `phases` | Le singole fasi dentro un modello, con il loro ordine di attraversamento. |
| 16 | `phase_transitions` | La storia dei passaggi di fase di un progetto: da dove, a dove, chi ha chiesto, chi ha approvato, perche'. |
| 17 | `email_messages` | La posta archiviata e collegata a una versione di prodotto, oppure in quarantena in attesa di essere smistata. |
| 18 | `email_attachments` | Gli allegati staccati dai messaggi e depositati nell'archivio per impronta, come tutti gli altri file. |
| 19 | `audit_logs` | Il registro di chi ha fatto che cosa, su quale oggetto, quando e da quale indirizzo. Si scrive e non si tocca piu'. |

---

## 4. Dettaglio delle tabelle

### 4.1 Persone e accessi

#### `users` — le persone che usano Aurora

| Colonna | Tipo | Note |
|---|---|---|
| `username` | varchar(50) | `NN` `UQ`. Attributo, non chiave: cambiarlo non spezza niente. |
| `first_name`, `last_name` | varchar(80) | `NN` |
| `email` | varchar(255) | `NN` `UQ`. Serve per le notifiche. |
| `password_hash` | varchar(255) | `NN`. Impronta argon2. La password in chiaro non entra nel database in nessuna forma. |
| `must_change_password` | boolean | `NN`, vero di partenza. |
| `is_active` | boolean | `NN`, vero di partenza. Sostituisce la cancellazione. |
| `global_role` | `global_role` | `NN`. `creatore` o `utente`. |

#### `user_sessions` — le sessioni aperte

| Colonna | Tipo | Note |
|---|---|---|
| `user_id` | UUID | `NN` `IX` -> `users.id` |
| `token_hash` | varchar(64) | `NN` `UQ`. Impronta SHA-256 del gettone consegnato al browser, non il gettone. |
| `kind` | `session_kind` | `NN`. `sessione` (dura quanto il browser) o `ricordami` (sopravvive alla chiusura). |
| `expires_at` | timestamptz | `NN` `IX` |
| `revoked_at` | timestamptz | Valorizzata all'uscita o quando un amministratore butta fuori la sessione. |
| `ip` | varchar(45) | 45 caratteri: la lunghezza massima di un IPv6 che incapsula un IPv4. |
| `user_agent` | varchar(400) | Per far riconoscere all'utente le proprie sessioni. |

#### `login_attempts` — i tentativi di accesso

| Colonna | Tipo | Note |
|---|---|---|
| `username` | varchar(50) | `NN`. Il nome **scritto**, come stringa: meta' dei tentativi interessanti riguarda nomi utente che non esistono, e un collegamento non potrebbe rappresentarli. |
| `success` | boolean | `NN` |
| `ip` | varchar(45) | |

Due indici composti, `(username, created_at)` e `(ip, created_at)`: le uniche
due domande che si fanno a questa tabella sono "quanti tentativi falliti da
questo nome / da questo indirizzo negli ultimi minuti".

### 4.2 Anagrafiche

#### `customers` — i clienti

| Colonna | Tipo | Note |
|---|---|---|
| `name` | varchar(160) | `NN` |
| `code` | varchar(20) | `NN` `UQ`. La sigla breve usata in azienda. |
| `notes` | text | |
| `is_active` | boolean | `NN`, vero di partenza. |

#### `contacts` — le persone presso un cliente

| Colonna | Tipo | Note |
|---|---|---|
| `customer_id` | UUID | `NN` `IX` -> `customers.id` |
| `name` | varchar(160) | `NN` |
| `email` | varchar(255) | `IX`, **non** unica: la stessa casella puo' essere il riferimento di piu' persone. |
| `role` | varchar(120) | Annotazione libera ("responsabile acquisti"), non un valore su cui il programma decida. |
| `is_active` | boolean | `NN`, vero di partenza. |

### 4.3 Prodotti

#### `products` — i prodotti

| Colonna | Tipo | Note |
|---|---|---|
| `code` | varchar(60) | `NN` `UQ`. Il codice parlante, per esempio `RMS1100-24-110SW`. |
| `customer_id` | UUID | `NN` `IX` -> `customers.id`. Vedi la nota 6.1. |
| `description` | text | |
| `code_parts` | jsonb | `NN`, `{}` di partenza. Il codice scomposto negli elementi riconosciuti. E' un dato **ricavato**: comodo per cercare, mai la fonte della verita'. |
| `is_active` | boolean | `NN`, vero di partenza. |

#### `product_versions` — le versioni di un prodotto

| Colonna | Tipo | Note |
|---|---|---|
| `product_id` | UUID | `NN` `IX` -> `products.id` |
| `version_number` | integer | `NN`. Contatore, non un numero di rilascio: 1, 2, 3, non "1.0.2". |
| `lifecycle_state` | `lifecycle_state` | `NN` `IX`. `in_sviluppo`, `rilasciato`, `in_produzione`, `superato`, `obsoleto`. |
| `derived_from_id` | UUID | `IX` -> `product_versions.id`. Autoriferimento, nullo per la prima versione. |
| `derivation_reason` | text | Perche' e' stata derivata, scritto da una persona. |
| `released_at` | timestamptz | Quando e' passata a `rilasciato`. |

Vincolo di unicita' su `(product_id, version_number)`: due volte la "versione
2" dello stesso prodotto non devono esistere. E' verificato da
`tests/test_models.py`.

### 4.4 Progetti

#### `projects` — il lavoro su una versione

| Colonna | Tipo | Note |
|---|---|---|
| `product_version_id` | UUID | `NN` `UQ` -> `product_versions.id`. L'unicita' e' quello che rende il legame uno-a-uno. |
| `project_manager_id` | UUID | `NN` `IX` -> `users.id` |
| `phase_template_id` | UUID | `NN` `IX` -> `phase_templates.id`. Resta quello scelto alla nascita, anche se il modello viene poi sostituito. |
| `current_phase_id` | UUID | `IX` -> `phases.id`. Nullo solo fra la creazione del progetto e l'ingresso nella prima fase. |
| `standards` | jsonb | `NN`, `[]` di partenza. Le norme applicabili: partono da quelle del modello e si possono allargare o restringere sul singolo progetto. |
| `opened_at` | timestamptz | `NN` |
| `closed_at` | timestamptz | Un progetto si chiude, non si cancella. |

#### `assignments` — chi lavora a che cosa

| Colonna | Tipo | Note |
|---|---|---|
| `project_id` | UUID | `NN` `IX` -> `projects.id` |
| `user_id` | UUID | `NN` `IX` -> `users.id` |
| `project_role` | `project_role` | `NN`. `project_manager`, `ingegnere`, `lettore`. |
| `assigned_by_id` | UUID | `NN` -> `users.id`. Chi ha dato l'incarico. |
| `revoked_at` | timestamptz | Vedi la nota 6.2. |
| `revoked_by_id` | UUID | -> `users.id` |

Indice unico **parziale** su `(project_id, user_id)` limitato alle righe con
`revoked_at IS NULL`: una persona ha al massimo un ruolo **attivo** per
progetto (due ruoli contemporanei renderebbero ambiguo il calcolo dei
permessi), ma puo' essere riassegnata dopo una revoca, e tutta la storia
precedente resta nella tabella.

### 4.5 Permessi

#### `classifications` — le classi di riservatezza

| Colonna | Tipo | Note |
|---|---|---|
| `name` | varchar(60) | `NN` `UQ`. Tecnico, Commerciale, Qualità, Amministrativo. |
| `description` | text | |
| `sort_order` | integer | `NN`. Ordine negli elenchi. |

#### `permission_rules` — la matrice

| Colonna | Tipo | Note |
|---|---|---|
| `project_role` | `project_role` | `NN` |
| `classification_id` | UUID | `NN` `IX` -> `classifications.id` |
| `can_view` | boolean | `NN`, falso di partenza. Vedere che il documento esiste e scaricarlo. |
| `can_upload` | boolean | `NN`, falso di partenza. Caricare una versione nuova o un documento nuovo. |
| `can_edit` | boolean | `NN`, falso di partenza. Cambiare titolo, tipo, stato; ritirare il documento. |

Unicita' su `(project_role, classification_id)`. La matrice ha **tutte** e
dodici le caselle, comprese quelle con tutti i permessi a falso: una casella
che dice "no" e' una decisione, una casella che manca e' una dimenticanza, e a
distanza di mesi non si distinguono. La matrice di partenza sta in
`scripts/seed.py`.

### 4.6 Documenti

#### `documents` — il contenitore

| Colonna | Tipo | Note |
|---|---|---|
| `project_id` | UUID | `NN` `IX` -> `projects.id` |
| `title` | varchar(200) | `NN` |
| `doc_type` | varchar(80) | `NN`. "Schema elettrico", "Distinta base", "Offerta". Testo libero in R1; se serviranno valori controllati diventera' una tabella a se'. |
| `classification_id` | UUID | `NN` `IX` -> `classifications.id`. Obbligatoria: senza classificazione non si puo' decidere chi vede il documento. |
| `state` | `document_state` | `NN` `IX`. `bozza`, `in_verifica`, `rilasciato`, `superato`. |
| `checked_out_by_id` | UUID | -> `users.id`. Presa in carico: evita che due persone preparino in parallelo due versioni diverse dello stesso schema. |
| `checked_out_at` | timestamptz | |
| `deleted_at` | timestamptz | `IX`. Sostituisce la cancellazione. |
| `deleted_by_id` | UUID | -> `users.id` |

#### `document_versions` — i file

| Colonna | Tipo | Note |
|---|---|---|
| `document_id` | UUID | `NN` `IX` -> `documents.id` |
| `version_number` | integer | `NN` |
| `storage_hash` | varchar(64) | `NN` `IX`. Impronta SHA-256 del contenuto: da li' si ricava il percorso nell'archivio (D-004). |
| `original_filename` | varchar(255) | `NN`. Il nome che l'utente riconosce e con cui gli si restituisce il file. |
| `size_bytes` | bigint | `NN`. `bigint` e non `integer`: i 2 GB del tipo normale sono pochi per un file. |
| `mime_type` | varchar(120) | `NN` |
| `author_id` | UUID | `NN` `IX` -> `users.id` |
| `note` | text | Che cosa e' cambiato rispetto alla versione prima. |

Unicita' su `(document_id, version_number)`. Le righe di questa tabella non si
modificano mai: una versione caricata e' un fatto avvenuto, e se il file era
sbagliato si carica la versione dopo.

### 4.7 Fasi

#### `phase_templates` — i modelli di percorso

| Colonna | Tipo | Note |
|---|---|---|
| `name` | varchar(80) | `NN` |
| `description` | text | |
| `standards` | jsonb | `NN`, `[]` di partenza. |
| `is_active` | boolean | `NN`, vero di partenza. Dice se il modello e' proponibile per un progetto nuovo. |
| `version` | integer | `NN`, 1 di partenza. |

Unicita' su `(name, version)`. **I modelli sono immutabili**: non si corregge
un modello gia' usato, se ne crea una versione nuova. Un progetto aperto due
anni fa e' passato per le fasi di allora; se il modello si potesse modificare a
posteriori, la sua storia racconterebbe fasi che al tempo non esistevano e le
approvazioni registrate sarebbero riferite a passaggi mai avvenuti.

#### `phases` — le fasi di un modello

| Colonna | Tipo | Note |
|---|---|---|
| `phase_template_id` | UUID | `NN` `IX` -> `phase_templates.id` |
| `name` | varchar(80) | `NN` |
| `sort_order` | integer | `NN`. Ordine di attraversamento. |
| `description` | text | |

Unicita' su `(phase_template_id, sort_order)` e su `(phase_template_id, name)`.
Due modelli che hanno entrambi una fase chiamata "Concept" hanno due righe
distinte: e' la conseguenza dell'immutabilita' dei modelli.

#### `phase_transitions` — i passaggi

| Colonna | Tipo | Note |
|---|---|---|
| `project_id` | UUID | `NN` `IX` -> `projects.id` |
| `from_phase_id` | UUID | -> `phases.id`. Nullo per il primo passaggio: prima non c'era nessuna fase da cui uscire. |
| `to_phase_id` | UUID | `NN` -> `phases.id` |
| `requested_by_id` | UUID | `NN` -> `users.id` |
| `approved_by_id` | UUID | -> `users.id`. Nullo finche' il passaggio e' solo richiesto. |
| `reason` | text | |

Registro: le righe si aggiungono, non si modificano e non si tolgono. Messe in
fila per data raccontano tutta la storia del progetto, compresi i passi
indietro.

### 4.8 Posta

#### `email_messages` — i messaggi archiviati

| Colonna | Tipo | Note |
|---|---|---|
| `product_version_id` | UUID | `IX` -> `product_versions.id`. **Nullo solo** quando `assignment_state` vale `quarantena`. |
| `internet_message_id` | varchar(998) | `NN` `UQ`. L'intestazione `Message-ID`: l'unicita' evita di archiviare due volte lo stesso messaggio se la casella viene riletta. |
| `in_reply_to` | varchar(998) | Intestazione `In-Reply-To`. |
| `thread_references` | text | Intestazione `References` per intero: e' la catena di tutti i messaggi precedenti del filo e puo' essere lunghissima. |
| `sender` | varchar(320) | `NN` `IX` |
| `recipients` | jsonb | `NN`, `[]` di partenza. Elenco di oggetti, non una stringa: su un elenco si puo' cercare. |
| `subject` | varchar(500) | |
| `subject_parsed` | jsonb | `NN`, `{}` di partenza. L'oggetto scomposto, per esempio il codice prodotto trovato dentro. Dato ricavato, serve a smistare. |
| `sent_at` | timestamptz | `IX`. Quando e' stato spedito, secondo il messaggio. |
| `received_at` | timestamptz | `NN` `IX`. Quando lo abbiamo ricevuto noi. Sono due cose diverse e possono distare parecchio. |
| `storage_hash` | varchar(64) | `NN` `IX`. Impronta del file `.eml` completo: l'originale si conserva intero, le colonne qui sopra sono una copia comoda per cercare. |
| `body_text` | text | Corpo in testo semplice, per la ricerca a parole. |
| `assignment_state` | `email_assignment_state` | `NN` `IX`. `automatica`, `manuale`, `quarantena`. |
| `assigned_by_id` | UUID | -> `users.id`. Chi ha smistato a mano. |

#### `email_attachments` — gli allegati

| Colonna | Tipo | Note |
|---|---|---|
| `email_message_id` | UUID | `NN` `IX` -> `email_messages.id` |
| `filename` | varchar(255) | `NN` |
| `storage_hash` | varchar(64) | `NN` `IX`. Lo stesso datasheet allegato a venti mail occupa un file solo. |
| `size_bytes` | bigint | `NN` |
| `mime_type` | varchar(120) | `NN` |

Un allegato **non** e' un documento di progetto. Se merita di diventarlo,
qualcuno lo promuove creando un `document`: e' un gesto voluto, non
automatico, perche' un allegato e' quello che ha mandato qualcun altro mentre
un documento e' quello di cui l'azienda risponde.

### 4.9 Tracciabilita'

#### `audit_logs` — il registro delle operazioni

| Colonna | Tipo | Note |
|---|---|---|
| `occurred_at` | timestamptz | `NN` `IX`. Quando il fatto e' successo. |
| `user_id` | UUID | -> `users.id`. **Puo' essere nullo**: certe operazioni le fa il programma da solo, per esempio un lavoro pianificato di notte. Meglio nullo che una persona finta. |
| `action` | varchar(80) | `NN`. In inglese e in forma breve: `document.upload`, `project.close`, `user.login`. |
| `entity_type` | varchar(60) | `NN`. Il nome della tabella: `documents`, `projects`, `users`. |
| `entity_id` | UUID | UUID **senza chiave esterna**: deve poter puntare a qualunque tabella, e una chiave esterna punta a una tabella sola. In piu' impedirebbe di registrare operazioni su righe che al momento della registrazione non esistono ancora o non esistono piu'. |
| `old_value`, `new_value` | jsonb | Solo i campi cambiati, non la riga intera. |
| `ip` | varchar(45) | |

Due indici composti: `(entity_type, entity_id, occurred_at)` e
`(user_id, occurred_at)`, cioe' "tutto quello che e' successo a questo oggetto"
e "tutto quello che ha fatto questa persona", in ordine di tempo.

`occurred_at` e `created_at` quasi sempre coincidono e restano comunque due
colonne diverse, perche' dicono due cose diverse: la prima quando il fatto e'
successo, la seconda quando la riga e' stata scritta. Se un giorno le
registrazioni verranno scritte in differita, la differenza fra le due sara'
l'unico modo di rimettere i fatti nell'ordine giusto.

---

## 5. I tipi enumerati

Sei tipi enumerati veri di PostgreSQL. Il nome della classe Python e' in
inglese, come tutti gli identificatori; il **valore** e' in italiano perche'
non e' un identificatore ma un dato scritto nel database e mostrato all'utente.
Stanno tutti in `app/models/enums.py`.

| Tipo | Valori | Usato da |
|---|---|---|
| `global_role` | `creatore`, `utente` | `users.global_role` |
| `session_kind` | `sessione`, `ricordami` | `user_sessions.kind` |
| `lifecycle_state` | `in_sviluppo`, `rilasciato`, `in_produzione`, `superato`, `obsoleto` | `product_versions.lifecycle_state` |
| `project_role` | `project_manager`, `ingegnere`, `lettore` | `assignments.project_role`, `permission_rules.project_role` |
| `document_state` | `bozza`, `in_verifica`, `rilasciato`, `superato` | `documents.state` |
| `email_assignment_state` | `automatica`, `manuale`, `quarantena` | `email_messages.assignment_state` |

Aggiungere o togliere un valore vuole una migrazione, non una modifica di
`enums.py`: il tipo vive nel database. Vedi anche il commento in cima alla
migrazione `897359b06e69`, che spiega perche' i tipi vengono creati
esplicitamente e cancellati a mano in discesa.

---

## 6. Scelte prese qui, da confermare

Tre punti in cui il modello dice qualcosa di piu' di quanto la sessione 2
avesse specificato. Sono segnalati perche' sono decisioni, non dettagli, e
cambiarli adesso costa una migrazione da poco.

### 6.1 `products.customer_id` e' obbligatorio

L'ipotesi e' che ogni prodotto sia sviluppato **per un cliente**: e' il dominio
dell'azienda, e il codice prodotto stesso contiene il riferimento. Se
servissero prodotti a catalogo, senza committente, la colonna va resa
facoltativa con una migrazione di una riga.

### 6.2 `assignments` ha `revoked_at` e `revoked_by_id`

L'elenco delle colonne della sessione non li prevedeva, ma senza di essi
un'assegnazione non si puo' togliere in nessun modo che rispetti il principio
2 (niente cancellazione fisica). Sono esattamente la coppia "data e autore" che
il principio richiede.

### 6.3 `documents.doc_type` e `documents.classification_id` sono obbligatori

Un documento senza classificazione non e' mostrabile a nessuno, perche' i
permessi si calcolano proprio su quella. Il tipo di documento e' testo libero
in R1: se in R2 servira' un elenco controllato, diventera' una tabella.

---

## 7. Che cosa non c'e' ancora

- **Distinte base e articoli**: sono del rilascio R3, di proposito non
  anticipati.
- **La funzione che filtra le righe disattivate.** Il principio 2 obbliga ogni
  interrogazione a escludere le righe con `deleted_at` valorizzato o
  `is_active` falso. Serve un modo semplice per non dimenticarsene; va deciso
  insieme alle prime interrogazioni vere, non prima (vedi D-006).

  Aggiornamento della sessione 3: per gli utenti il problema e' risolto in un
  punto solo, e vale la pena di sapere come. `auth.trova_sessione()` verifica
  `users.is_active` **dentro la stessa interrogazione** che cerca la sessione,
  e siccome ogni pagina protetta passa di li', un utente disattivato smette di
  funzionare ovunque senza che nessuna altra interrogazione debba ricordarsene
  (D-032). Non e' una soluzione generale - vale perche' c'e' un solo ingresso -
  ma e' il modello a cui guardare: **un controllo solo, sulla strada obbligata**,
  invece di un filtro ripetuto in venti punti.

  Fa eccezione l'elenco degli utenti in `/utenti`, che i disattivati li mostra
  apposta: e' la pagina da cui si riattivano.

- ~~**La scrittura nel registro di audit.**~~ Fatta nella sessione 3:
  `app/services/audit.py`, funzione `record()`. E' l'unica che scrive in
  `audit_logs`, come vuole D-018.
- ~~**Il ripristino della password di `admin`.**~~ Fatto nella sessione 3:
  `scripts/reimposta_password.py`.
