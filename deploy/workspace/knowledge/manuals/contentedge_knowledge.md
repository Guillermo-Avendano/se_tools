# Rocket ContentEdge Knowledge (Current Summary)

## Product

ContentEdge is Rocket Software enterprise content repository technology.
Product page:

https://www.rocketsoftware.com/en-us/products/contentedge

## Core Concepts

### Content Class

Logical document type definition and metadata scope.

### Index

Single metadata field used for archive/search constraints.

### Index Group

Mandatory set of related indexes.
When a workflow requires the group, all group members must be provided together.

### Archiving Policy

Configuration that controls extraction and metadata behavior during archive workflows.

## Repository Operations Used by the Agent

- List content classes
- List indexes and index groups
- Search documents
- Build document URL
- Search/get/delete archiving policies
- Import/export content classes, indexes, index groups
- Repository connectivity info

## Practical Constraints

- Some write-heavy or bulk operations are intentionally disabled in conversational flow.
- Retrieval quality depends on valid embedding model plus indexed knowledge in Qdrant.
- Operational commands in SE Tools should be generated from active context (tool/repo/operation/command).
