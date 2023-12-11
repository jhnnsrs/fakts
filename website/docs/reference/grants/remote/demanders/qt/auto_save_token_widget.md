---
sidebar_label: auto_save_token_widget
title: grants.remote.demanders.qt.auto_save_token_widget
---

## ShouldWeSaveDialog Objects

```python
class ShouldWeSaveDialog(QtWidgets.QDialog)
```

A dialog that asks the user if we should save the token or not

#### \_\_init\_\_

```python
def __init__(endpoint: FaktsEndpoint, token: str, *args, **kwargs) -> None
```

Constructor for ShouldWeSaveDialog

## AutoSaveTokenWidget Objects

```python
class AutoSaveTokenWidget(QtWidgets.QWidget)
```

A simple widget that asks the user if we should save the token or not

#### \_\_init\_\_

```python
def __init__(*args, **kwargs) -> None
```

Constructor for AutoSaveTokenWidget

#### ashould\_we\_save

```python
async def ashould_we_save(endpoint: FaktsEndpoint, token: str) -> bool
```

Should ask the user if we should save the user

