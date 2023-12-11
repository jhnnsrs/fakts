---
sidebar_label: auto_save_endpoint_widget
title: grants.remote.discovery.qt.auto_save_endpoint_widget
---

## ShouldWeSaveThisAsDefault Objects

```python
class ShouldWeSaveThisAsDefault(QtWidgets.QDialog)
```

A dialog that asks the user if we should save the ednpoint or not

#### \_\_init\_\_

```python
def __init__(stored: FaktsEndpoint, *args, **kwargs) -> None
```

Constructor for ShouldWeSaveDialog

## AutoSaveEndpointWidget Objects

```python
class AutoSaveEndpointWidget(QtWidgets.QWidget)
```

A simple widget that asks the user if we should save the endoint or not

#### \_\_init\_\_

```python
def __init__(*args, **kwargs) -> None
```

Constructor for AutoSaveEndpointWidget

#### ashould\_we\_save

```python
async def ashould_we_save(store: FaktsEndpoint) -> bool
```

Should ask the user if we should save the user

