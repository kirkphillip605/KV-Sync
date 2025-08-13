# src/ui/operationLogsDialog.py
import logging

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QPushButton, QSplitter, QTableView, QVBoxLayout, QWidget)

logger = logging.getLogger('vibe_manager')


class LogsTableModel(QAbstractTableModel):
    def __init__(self, log_data):
        super().__init__()
        self.log_data = log_data
        self._headers = ["ID", "Operation", "Start Time", "End Time", "Status", "Details"]

    def rowCount(self, parent = QModelIndex()):
        return len(self.log_data)

    def columnCount(self, parent = QModelIndex()):
        return len(self._headers)

    def data(self, index, role = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        row, col = index.row(), index.column()
        # Access data using index and column name directly
        column_name = self._headers [col]
        value = self.log_data [row] [col]
        return str(value) if value else "N/A"

    def headerData(self, section, orientation, role = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._headers [section]
        return None

    def update_data(self, new_log_data):
        self.beginResetModel()
        self.log_data = new_log_data
        self.endResetModel()

    def get_log_entry(self, row_index):
        return self.log_data [row_index] if 0 <= row_index < len(self.log_data) else None


class LogsDialog(QDialog):
    def __init__(self, db_manager, parent = None):
        super().__init__(parent)
        self.setWindowTitle("Operation Logs")
        self.db_manager = db_manager
        self.log_data, self.current_page, self.page_size, self.total_pages = [], 1, 20, 1
        self.search_term, self.operation_filter, self.detail_widgets = "", "", {}

        self.init_ui()
        self.load_logs()

    def init_ui(self):

        main_layout = QVBoxLayout(self)
        self.resize(1300, 700)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.create_top_section())
        splitter.addWidget(self.create_detail_section())
        splitter.setSizes([800, 800])

        main_layout.addWidget(splitter)
        main_layout.addWidget(self.create_button_box())  # Add button box here
        self.setLayout(main_layout)

    def create_top_section(self):
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)

        filter_layout = self.create_filter_layout()
        table_widget = self.create_table_widget()
        pagination_layout = self.create_pagination_layout()

        top_layout.addLayout(filter_layout)
        top_layout.addWidget(table_widget)
        top_layout.addLayout(pagination_layout)

        return top_widget

    def create_filter_layout(self):
        layout = QHBoxLayout()
        self.operation_filter_combo = QComboBox()
        self.operation_filter_combo.setMinimumContentsLength(16)
        self.operation_filter_combo.setMinimumWidth(200)
        self.operation_filter_combo.addItems(
            ["All Operations", "Get New Tracks", "Download New Tracks", "Validate Database", "Toggle Polling"])
        self.operation_filter_combo.currentIndexChanged.connect(self.apply_filters)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search logs...")
        self.search_bar.textChanged.connect(self.apply_filters)

        layout.addWidget(QLabel("Filter by Operation:"))
        layout.addWidget(self.operation_filter_combo)
        layout.addWidget(QLabel("Search:"))
        layout.addWidget(self.search_bar)
        return layout

    def create_table_widget(self):
        self.table_view = QTableView()
        self.table_model = LogsTableModel(self.log_data)
        self.table_view.setModel(self.table_model)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        header = self.table_view.horizontalHeader()
        for col in range(self.table_model.columnCount() - 1):  # Resize all columns to content, except last one
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.table_model.columnCount() - 1,
                                    QHeaderView.ResizeMode.Stretch)  # Details column to stretch

        self.table_view.selectionModel().currentChanged.connect(self.populate_detail_view)
        self.table_view.setAlternatingRowColors(True)  # Enable alternating row colors
        self.table_view.verticalHeader().setVisible(False)  # Hide vertical header
        self.table_view.setShowGrid(False)  # Remove grid lines
        return self.table_view

    def create_pagination_layout(self):
        layout = QHBoxLayout()
        self.prev_page_button = QPushButton("Previous Page")
        self.next_page_button = QPushButton("Next Page")
        self.page_label = QLabel("Page 1 of 1")

        self.prev_page_button.clicked.connect(self.prev_page)
        self.next_page_button.clicked.connect(self.next_page)

        layout.addWidget(self.prev_page_button)
        layout.addWidget(self.page_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.next_page_button)
        return layout

    def create_detail_section(self):
        detail_widget = QWidget()
        layout = QVBoxLayout(detail_widget)
        layout.addWidget(QLabel("<h3>Log Entry Details</h3>"))
        self.detail_grid_layout = QGridLayout()
        layout.addLayout(self.detail_grid_layout)
        return detail_widget

    def create_button_box(self):
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        return button_box

    def populate_detail_view(self, index):
        for widget in self.detail_widgets.values():
            widget.deleteLater()
        self.detail_widgets.clear()

        if index.isValid():
            log_entry = self.table_model.get_log_entry(index.row())
            if log_entry:
                row_data = {"ID": log_entry [0], "Operation": log_entry [1], "Status": log_entry [4],
                    # Status is at index 4
                    "Start Time": log_entry [2],  # Start Time is at index 2
                    "End Time": log_entry [3],  # End Time is at index 3
                    "Details": log_entry [5],  # Details - now included in grid
                }
                detail_row = 0
                for header, data in row_data.items():
                    self.add_detail_row(header, data, detail_row)
                    detail_row += 1

    def add_detail_row(self, header, data, row):
        header_label = QLabel(f"<b>{header}:</b>")
        data_label = QLabel(str(data) if data else "N/A")
        data_label.setWordWrap(True)
        self.detail_grid_layout.addWidget(header_label, row, 0, alignment=Qt.AlignmentFlag.AlignTop)
        self.detail_grid_layout.addWidget(data_label, row, 1, alignment=Qt.AlignmentFlag.AlignTop)
        self.detail_widgets [header] = data_label

    def load_logs(self):
        filters = {
            "operation": self.operation_filter_combo.currentText()} if self.operation_filter_combo.currentText() != "All Operations" else {}
        self.search_term = self.search_bar.text()
        self.log_data = self.db_manager.get_operation_logs(filters, self.search_term, self.current_page, self.page_size)
        self.table_model.update_data(self.log_data)
        self.update_pagination_label()
        self.update_pagination_buttons()

    def apply_filters(self):  # Re-add apply_filters method
        self.current_page = 1
        self.load_logs()

    def next_page(self):
        self.current_page += 1
        self.load_logs()

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.load_logs()

    def update_pagination_label(self):
        self.page_label.setText(f"Page {self.current_page} of {self.total_pages}")

    def update_pagination_buttons(self):
        self.prev_page_button.setEnabled(self.current_page > 1)
        self.next_page_button.setEnabled(self.current_page < self.total_pages)
