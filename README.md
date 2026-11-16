# Danbooru Tag Indexer for ComfyUI

An open-source ComfyUI extension for browsing and searching an offline Danbooru tag encyclopedia, saving favorite tags, and organizing personal tag collections.

The extension includes a bundled tag database and works offline without additional dependencies.

## Features

- Offline browsing and searching of Danbooru tags.
- Hierarchical categories and nested subgroups.
- Expandable tag descriptions and related entries.
- Search by tag name or description.
- Copy tag names directly to your clipboard.
- Save and remove favorite tags.
- Create and manage multiple saved-tag collections.
- Add and edit personal tags with custom descriptions and folders.
- Compact saved-tag cards with expandable descriptions.
- Resizable node interfaces.
- Persistent collections across ComfyUI sessions.

## Installation

1. Download or clone this repository.
2. Copy the `Danbooru-Tag-Indexer-Comfy-UI` folder into your ComfyUI `custom_nodes` directory.
3. Restart ComfyUI.
4. Refresh the ComfyUI interface using `Ctrl + F5` if necessary.

Expected installation structure:

```text
ComfyUI/
└── custom_nodes/
    └── Danbooru-Tag-Indexer-Comfy-UI/
        ├── __init__.py
        ├── catalog.py
        ├── navigation.py
        ├── data/
        └── web/
```

For ComfyUI Desktop, use its configured external `custom_nodes` directory.

No additional Python packages or build steps are required.

## Available Nodes

### Danbooru · Tag Index

Browse and search the bundled Danbooru tag database.

- Search tags by name or description.
- Navigate categories and nested tag groups.
- Expand tags to view descriptions and related entries.
- Copy tag names with normal spaces.
- Save tags to connected collections.

### Danbooru · Saved Tags

Manage your saved tags and personal collections.

- View saved tags with short descriptions.
- Expand cards to read complete descriptions and folder paths.
- Remove saved tags.
- Create and edit personal tags.
- Organize tags into separate collections.
- Copy saved tag names.

## Connecting the Nodes

Connect the **tag_library** output of the Tag Index node to the **tag_library** input of the Saved Tags node.

```text
Danbooru · Tag Index
        │
        │ tag_library
        ▼
Danbooru · Saved Tags
```

Click the star beside a tag to save it to the connected collection.

Changes are saved immediately without executing the workflow.

Multiple Saved Tags nodes can connect to the same Tag Index node. Each connected collection receives starred tags.

Direct connections within the same graph are supported. Reroute and cross-subgraph connections are not currently supported.

## Saved Collections

Each new Saved Tags node creates a collection.

You can create additional collections or select existing ones using the collection dropdown.

Saved tags and personal entries are stored locally and remain available between sessions.

## Offline Database

The extension includes a bundled database containing approximately:

- **155,665 tags**
- **48,680 category and section entries**

The database is available offline and does not require downloading additional tag data.

The extension does not automatically update the database or retrieve live content from Danbooru.

## Data Storage

Personal collections and saved tags are stored in ComfyUI's user directory.

Typical location:

```text
ComfyUI/user/default/danbooru-tag-indexer/saved.sqlite
```

Back up `saved.sqlite` to preserve your collections when moving between installations.

## Limitations

- The extension is intended for tag browsing and reference, not automatic prompt generation.
- The bundled tag database is static.
- Tag saving between nodes requires a direct connection.
- Reroute nodes and cross-subgraph connections are not supported.

## License & Credits

Licensed under the [Apache License 2.0](LICENSE).

Tag and wiki content is sourced from [Danbooru](https://danbooru.donmai.us/) and remains subject to its contributors' respective terms.

This project is independent and is not affiliated with Danbooru or Comfy Org.