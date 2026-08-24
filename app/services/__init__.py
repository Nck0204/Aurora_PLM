"""Logica applicativa: le operazioni che non sono ne' rotte HTTP ne' tabelle.

Qui finiranno per esempio il calcolo dell'impronta dei file caricati, l'invio
della posta e la registrazione delle operazioni nell'audit trail.

La regola e' semplice: le rotte in app/routers leggono la richiesta e
compongono la risposta; il lavoro vero lo fanno le funzioni di questa cartella.
Cosi' la stessa operazione puo' essere richiamata da una pagina web, da un
lavoro pianificato o da un test, senza duplicare codice.
"""
