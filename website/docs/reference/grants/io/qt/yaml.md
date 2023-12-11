---
sidebar_label: yaml
title: grants.io.qt.yaml
---

## NoFileSelected Objects

```python
class NoFileSelected(GrantError)
```

Raised when no file was selected.

## QtSelectYaml Objects

```python
class QtSelectYaml(QtWidgets.QFileDialog)
```

Represents a File Dialog that selects YAML files.

Methods
-------
ask(parent=None)
    Opens the file dialog and returns the selected file path.

#### \_\_init\_\_

```python
def __init__(*args, **kwargs) -> None
```

A File Dialog that selects YAML files.

#### ask

```python
@classmethod
def ask(cls: Type["QtSelectYaml"],
        parent: Optional[QtWidgets.QWidget] = None) -> str
```

Opens the file dialog and returns the selected file path.

Parameters
----------
parent : QWidget, optional
    The parent widget of the file dialog.

Returns
-------
str
    The file path of the selected file.

## WrappingWidget Objects

```python
class WrappingWidget(QtWidgets.QWidget)
```

A Widget that wraps the file selection process.

Attributes
----------
get_file_coro : QtCoro
    The coroutine that opens the file dialog and returns the selected file path
    (a call to `get_file_coro.acall()` will return a future that resolves to the selected file path
    or rejects with a `NoFileSelected` error).

Methods
-------
open_file(future: QtFuture)
    Opens the file dialog and resolves or rejects the future based on the selected file path.

#### \_\_init\_\_

```python
def __init__(*args, **kwargs) -> None
```

A Widget that wraps the file selection process.

#### open\_file

```python
def open_file(future: QtFuture) -> None
```

Opens the file dialog and resolves or rejects the future based on the selected file path.

Parameters
----------
future : QtFuture
    The future that will be resolved or rejected based on the selected file path.

#### aask

```python
async def aask() -> str
```

Opens the file dialog and returns the selected file path.

Returns
-------
str
    The file path of the selected file.

## FileWidget Objects

```python
@runtime_checkable
class FileWidget(Protocol)
```

A Protocol that represents a widget

that wraps the file selection process.
It can be used to create a custom widget that wraps the file selection process.

#### aask

```python
async def aask() -> str
```

Opens the file dialog and returns the selected file path.

Parameters
----------
parent : QWidget, optional
    The parent widget of the file dialog.

Returns
-------
str
    The file path of the selected file.

## QtYamlGrant Objects

```python
class QtYamlGrant(BaseModel)
```

Represent a Grant that allows the user to select a YAML file.

Attributes
----------
widget : WrappingWidget
    The widget that wraps the file selection process.

Methods
-------
aload(request: FaktsRequest)
    Asynchronously loads the YAML file and returns the configuration.

#### aload

```python
async def aload(request: FaktsRequest) -> Dict[str, FaktValue]
```

Loads the YAML file and returns the configuration.

Parameters
----------
request : FaktsRequest
    The request object that may contain additional information needed for loading the YAML file.

Returns
-------
dict
    The configuration loaded from the YAML file.

## Config Objects

```python
class Config()
```

Pydantic Config class for QtYamlGrant.

