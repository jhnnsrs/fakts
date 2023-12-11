---
sidebar_label: selectable_beacon
title: grants.remote.discovery.qt.selectable_beacon
---

## SelfScanWidget Objects

```python
class SelfScanWidget(QtWidgets.QWidget)
```

A widget that allows the user to scan for beacons

    It has a line edit and a button. When the button is clicked,
    the line edit is scanned for a url, and if it is a valid url,
    a beacon is emitted with the url.
from .utils import discover_url

    No validation is done on the url, so it is up to the user to
    enter a valid url.

#### \_\_init\_\_

```python
def __init__(*args, **kwargs) -> None
```

Constructor for SelfScanWidget

#### on\_add

```python
def on_add() -> None
```

Called when the button is clicked

## FaktsEndpointButton Objects

```python
class FaktsEndpointButton(QtWidgets.QPushButton)
```

A button that represents a FaktsEndpoint

It has a title and a subtitle, and when clicked, emits
a signal with the endpoint

#### \_\_init\_\_

```python
def __init__(endpoint: FaktsEndpoint,
             parent: Optional[QtWidgets.QWidget] = None) -> None
```

Constructor for FaktsEndpointButton

#### initUI

```python
def initUI() -> None
```

Initialize UI elements

#### paintEvent

```python
def paintEvent(event: Any) -> None
```

Paint the button with the given style, title and subtitle

#### enterEvent

```python
def enterEvent(event: Any) -> None
```

Sets the cursor to pointing hand when hovering over the button

#### leaveEvent

```python
def leaveEvent(event: Any) -> None
```

Sets the cursor to arrow when not hovering over the button

#### mousePressEvent

```python
def mousePressEvent(event: Any) -> None
```

Sets the button to pressed when clicked

#### mouseReleaseEvent

```python
def mouseReleaseEvent(event: Any) -> None
```

Sets the button to not pressed when released

#### on\_clicked

```python
def on_clicked() -> None
```

Called when the button is clicked

## SelectBeaconWidget Objects

```python
class SelectBeaconWidget(QtWidgets.QDialog)
```

A widget that allows the user to select a beacon

It has a list of buttons, each representing a beacon.
When a button is clicked, a signal is emitted with the beacon

#### \_\_init\_\_

```python
def __init__(*args,
             settings: Optional[QtCore.QSettings] = None,
             **kwargs) -> None
```

Constructor for SelectBeaconWidget

#### clearLayout

```python
def clearLayout(layout: QtWidgets.QVBoxLayout) -> None
```

Clear the layout

#### clear\_endpoints

```python
def clear_endpoints() -> None
```

Clear the endpoints

#### show\_me

```python
def show_me() -> None
```

A function that shows the widget

#### show\_error

```python
def show_error(error: Exception) -> None
```

Show an error message

Parameters
----------
error : Exception
    Display the error message

#### demand\_selection\_of\_endpoint

```python
def demand_selection_of_endpoint(future: QtFuture) -> None
```

Is called when the user should select an endpoint. I.e. when the demander
is called programmatically

#### on\_endpoint\_clicked

```python
def on_endpoint_clicked(item: FaktsEndpoint) -> None
```

Called when an endpoint button is clicked

Will resolve the future with the endpoint

#### on\_reject

```python
def on_reject() -> None
```

Called when the user rejects the dialog

Will reject the future

#### closeEvent

```python
def closeEvent(event: Any) -> None
```

Called when the window is closed. Will automatically reject the future

#### on\_new\_endpoint

```python
def on_new_endpoint(config: FaktsEndpoint) -> None
```

A callback that is called when a new endpoint is discovered

Creates a button for the endpoint and adds it to the layout

#### wait\_first

```python
async def wait_first(*tasks) -> Any
```

Return the result of first async task to complete with a non-null result

## QtSelectableDiscovery Objects

```python
class QtSelectableDiscovery(BaseModel)
```

A QT based discovery that will cause the user to select an endpoint
from a list of network discovered endpoints, as well as endpoints
that the user manually enters.

#### broadcast\_port

The port the broadcast on

#### bind

The address to bind to

#### strict

Should we error on bad Beacons

#### discovered\_endpoints

A cache of discovered endpoints

#### ssl\_context

An ssl context to use for the connection to the endpoint

#### emit\_endpoints

```python
async def emit_endpoints() -> None
```

A long running task that will emit endpoints that are discovered
through the network and emit them to be displayed in the widget.

#### await\_user\_definition

```python
async def await_user_definition() -> Optional[FaktsEndpoint]
```

Await the user to define a beacon. This will cause the widget to listen for
user input.

Returns
-------
FaktsEndpoint
    The endpoint that the user defined

#### adiscover

```python
async def adiscover(request: FaktsRequest) -> FaktsEndpoint
```

Discover the endpoint

This discovery will cause the attached widget to be shown, and
then the user is able to select and endpoint that is discovered
automatically or by the user.

Parameters
----------
request : FaktsRequest
    The request to use for the discovery process (is not used)

Returns
-------
FaktsEndpoint
    A valid endpoint

## Config Objects

```python
class Config()
```

Pydantic Config

