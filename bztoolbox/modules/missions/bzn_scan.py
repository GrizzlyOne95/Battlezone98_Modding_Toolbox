import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from battlezone.bzn.scan import (  # noqa: F401 - re-exported for legacy callers
    STOCK_ODF_LIST, STOCK_SET, BinaryFieldType, BZNParser,
)


class BZNAnalyzer:
    def __init__(self, root):
        self.root = root
        self.root.title("BZ98R BZN Analyzer")
        self.root.geometry("800x600")
        self.current_file = None
        self.data = []

        # UI Controls
        frame = tk.Frame(root)
        frame.pack(pady=10, fill=tk.X)
        
        tk.Button(frame, text="Load BZN", command=self.load_file).pack(side=tk.LEFT, padx=10)
        self.custom_only = tk.BooleanVar()
        tk.Checkbutton(frame, text="Custom ODFs Only", variable=self.custom_only, command=self.refresh).pack(side=tk.LEFT)
        
        self.status_lbl = tk.Label(root, text="Select a file to begin", fg="gray")
        self.status_lbl.pack()

        # Table (Treeview)
        columns = ("status", "type", "filename")
        self.tree = ttk.Treeview(root, columns=columns, show='headings')
        
        self.tree.heading("status", text="Status", command=lambda: self.sort_column("status", False))
        self.tree.heading("type", text="Type", command=lambda: self.sort_column("type", False))
        self.tree.heading("filename", text="Filename", command=lambda: self.sort_column("filename", False))
        
        self.tree.column("status", width=100)
        self.tree.column("type", width=100)
        self.tree.column("filename", width=550)
        
        # Color tags for Missing items
        self.tree.tag_configure('missing', foreground='red')
        self.tree.tag_configure('stock', foreground='gray')

        self.tree.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

    def load_file(self):
        path = filedialog.askopenfilename(filetypes=[("BZN Files", "*.bzn")])
        if path:
            self.current_file = path
            self.status_lbl.config(text=f"File: {os.path.basename(path)}", fg="black")
            self.analyze()

    def analyze(self):
        self.data = []
        directory = os.path.dirname(self.current_file)
        
        try:
            parser = BZNParser(self.current_file)
            matches = parser.parse()

            for odf_base in matches:
                filename = f"{odf_base}.odf"
                is_stock = filename.lower() in STOCK_SET
                exists = os.path.exists(os.path.join(directory, filename))
                
                status = "OK" if exists else "MISSING"
                odf_type = "Stock" if is_stock else "Custom"
                self.data.append((status, odf_type, filename))

            self.refresh()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def refresh(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
            
        filtered_data = self.data
        if self.custom_only.get():
            filtered_data = [item for item in self.data if item[1] == "Custom"]

        for item in filtered_data:
            tags = ()
            if item[0] == "MISSING": tags = ('missing',)
            elif item[1] == "Stock": tags = ('stock',)
            
            self.tree.insert('', tk.END, values=item, tags=tags)

    def sort_column(self, col, reverse):
        # Map column names to index
        idx = {"status": 0, "type": 1, "filename": 2}[col]
        
        # Get data from tree and sort
        l = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]
        l.sort(reverse=reverse)

        for index, (val, k) in enumerate(l):
            self.tree.move(k, '', index)

        # Reverse sort next time
        self.tree.heading(col, command=lambda: self.sort_column(col, not reverse))

if __name__ == "__main__":
    root = tk.Tk()
    app = BZNAnalyzer(root)
    root.mainloop()