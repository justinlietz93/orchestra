from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class WorkbenchForm(QWidget):
    """Passive widget tree for the user-only Research Workbench."""

    def __init__(self, graph_node_path: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel("USER RESEARCH WORKBENCH")
        title.setObjectName("title")
        layout.addWidget(title)

        badges = QHBoxLayout()
        self.origin_badge = self._badge("USER RESEARCH")
        self.lifecycle_badge = self._badge("CREATED")
        self.exposure_badge = self._badge("NOT PROVIDED")
        badges.addWidget(self.origin_badge)
        badges.addWidget(self.lifecycle_badge)
        badges.addWidget(self.exposure_badge)
        badges.addStretch(1)
        layout.addLayout(badges)

        warning = QLabel(
            "This user-only sidecar cannot advance p-b-v coordinates, change the "
            "active role, deliver artifacts to agents, or promote claims into canon."
        )
        warning.setObjectName("muted")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        layout.addWidget(self._label("GRAPH LAUNCH POINT"))
        node = QLineEdit(graph_node_path)
        node.setReadOnly(True)
        layout.addWidget(node)

        layout.addWidget(self._label("CAMPAIGN OBJECTIVE"))
        self.objective = QLineEdit()
        self.objective.setPlaceholderText(
            "What do you want to establish from these selected project artifacts?"
        )
        layout.addWidget(self.objective)

        artifact_header = QHBoxLayout()
        artifact_header.addWidget(self._label("EXPLICIT RUN ARTIFACTS"))
        artifact_header.addStretch(1)
        self.add_button = QPushButton("Add project files")
        self.remove_button = QPushButton("Remove selected")
        artifact_header.addWidget(self.add_button)
        artifact_header.addWidget(self.remove_button)
        layout.addLayout(artifact_header)

        self.artifact_list = QListWidget()
        self.artifact_list.setMaximumHeight(145)
        layout.addWidget(self.artifact_list)

        run_row = QHBoxLayout()
        self.run_button = QPushButton("Create campaign and immutable run")
        self.run_button.setObjectName("primary")
        self.run_status = QLabel("No run created")
        self.run_status.setObjectName("muted")
        run_row.addWidget(self.run_button)
        run_row.addWidget(self.run_status, 1)
        layout.addLayout(run_row)

        layout.addWidget(self._label("HASHED SUMMARY"))
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setPlaceholderText(
            "The immutable internal-only run summary will appear here."
        )
        layout.addWidget(self.summary, 1)

        attach_row = QHBoxLayout()
        self.target = QComboBox()
        self.target.setMinimumWidth(300)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Optional attachment note")
        self.attach_button = QPushButton("Attach summary to p-b-v")
        self.attach_button.setEnabled(False)
        attach_row.addWidget(QLabel("Attach to"))
        attach_row.addWidget(self.target)
        attach_row.addWidget(self.note, 1)
        attach_row.addWidget(self.attach_button)
        layout.addLayout(attach_row)

    @staticmethod
    def _badge(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("researchBadge")
        return label

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("eyebrow")
        return label
