---
sidebar_label: utils
title: grants.remote.demanders.utils
---

#### could\_copy\_to\_clipboard

```python
def could_copy_to_clipboard(text: str) -> bool
```

Copies text to clipboard if possible

This function tries to copy the text to the clipboard.
If it fails, it returns False, otherwise True.

Parameters
----------
text : str
    The text to copy to the clipboard

Returns
-------
bool
    Could the text be copied to the clipboard?

