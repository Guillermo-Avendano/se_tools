# SE-Content-Agent: "How To" Guide

## Guidelines

- SE-Content-Agent exclusively handles **Content Classes**, **Indexes**, and **Archiving Policies**.

### Archiving Policies
- Automatic policy creation for archiving includes only **section** and **version** mapping.
- Each field referenced in the prompt MUST specify the starting position of the element:  
  the **column** (from the left) and **line** (from the top).
- **Note:** Reports with ASA characters have not been tested yet.

## How to Create an Archiving Policy and Store the Source Document

Create an archiving policy from `workspace/tmp/CO17-2007-10-08.TXT`, where:

- Positionally extract `"4022"` from **line 1, column 9** as the value for the **SECTION**.
- To the right of **"FECHA EJECUCION"**, extract the date from **line 2, column 106**  
  in **DD‑MM‑YYYY** format and use it as the **VERSION**.
- The archiving policy name must be **AC001_POLICY**.
- Store `workspace/tmp/CO17-2007-10-08.TXT` in the **AC001 Content Class** using the **AC001_POLICY** archiving policy.

## How to Archive a document using metadata

Store `workspace/tmp/CO17-2007-10-08.TXT` in the **AC001 Content Class**, using the indexes LOAN=123, CUST_ID=101, and SECTION=ABC.

**Rules:**
- Every index name must be a valid repository index.
- If an index belongs to a compound group, all members of the group must be provided.
- If **SECTION** is not specified, the filename (without path or extension, up to 20 characters,
  replacing spaces and non-alphanumeric characters with `_`) is used as the default.
  Example: `CO17-2007-10-08.TXT` → SECTION = `CO17-2007-10-08` 

---

## List & Compare Content Classes or Indexes

List content classes from SOURCE (default):

> List the content classes

List content classes from TARGET:

> List the content classes in TARGET

Compare content classes between both repositories:

> List the content classes in SOURCE and TARGET and tell me if they are the same

Compare indexes between both repositories:

> List the indexes in SOURCE and TARGET and compare them

### Compare & Migrate Missing Definitions

Find what's in SOURCE but not in TARGET, and migrate the missing definitions:

> Compare the content classes, indexes, and index groups between SOURCE and TARGET. Export what's missing in TARGET and import it.

Step by step (interactive):

> List the content classes in SOURCE and TARGET and tell me what's missing in TARGET

> Export the missing content classes and import them into TARGET

The agent will:
1. List objects in both repositories
2. Compare by ID — show differences
3. Export only the missing items from SOURCE
4. Ask for confirmation before importing
5. Import into TARGET (indexes first, then index groups, then content classes)

### Selective Import

Import content classes from a previously exported file:

> Import the content classes from workspace/exports/content_class_20260318_150316.json into TARGET

Import indexes:

> Import the indexes from workspace/exports/indexes_20260318_150316.json into TARGET

Import index groups:

> Import the index groups from workspace/exports/index_groups_20260318_150316.json into TARGET

---

## Export & Import Operations

All export tools read from **SOURCE** by default.  
The import tool writes to **TARGET** by default.  
Both accept a `repo` parameter ("source" or "target") to override the default.

### Export Content Classes

Export all content classes:

> Export the content classes

Export content classes whose ID starts with "AC":

> Export the content classes with filter AC*

Export a single content class by exact ID:

> Export the content class AC001

### Export Indexes

Export all indexes:

> Export the indexes

Export indexes whose name starts with "Cust":

> Export the indexes with filter Cust*

### Export Index Groups

Export all index groups:

> Export the index groups

Export index groups whose name starts with "Person":

> Export the index groups with filter Person*

### Export Archiving Policy

Export a specific archiving policy to a JSON file in `workspace/archiving_policies/`:

> Export the archiving policy AC001_POLICY

### Export All (Full Repository Backup)

Export all admin objects (content classes, indexes, index groups, and archiving policies) to a timestamped directory:

> Export all objects

This creates `workspace/export_<YYYYMMDD_HHMMSS>/` containing subdirectories per object type plus a `manifest.json`.

### Import All (from Export Directory)

Import into TARGET (default):

> Import the export from workspace/export_20260318_150316

Import into SOURCE (explicit):

> Import the export from workspace/export_20260318_150316 into SOURCE

The agent will show the manifest contents and the destination repository name/URL, then ask for confirmation before proceeding.  
Import order: indexes → index groups → content classes → archiving policies.  
Objects that already exist on the destination are skipped.

### Full Export → Import Workflow

Migrate all admin objects from SOURCE to TARGET:

> Export all objects and then import them into TARGET

This will:
1. Export everything from SOURCE to `workspace/export_<timestamp>/`
2. Show the manifest and ask for confirmation
3. Import into TARGET

---

## How to Reset Chat History Mid-Conversation

When previous chat history (export/import results, search results, etc.) interferes with a new request, prefix your message with a **reset phrase** to clear the history before processing.

**Supported reset phrases** (at the start of the message):

| Español | English |
|---|---|
| nuevo tema | new topic |
| nueva conversación | start over |
| olvida lo anterior | forget previous |
| limpiar historial | clear history |
| empezar de nuevo | reset |

**Examples:**

> nuevo tema, archiva workspace/tmp/CO17-2007-10-08.TXT en AC001 con LOAN=123

> new topic: export all objects

> reset

The reset phrase is stripped from the message — the rest is processed normally with an empty history. If the message contains only the reset phrase (e.g. just "nuevo tema"), the agent acknowledges the reset.
