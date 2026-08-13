import pandas as pd
from typing import List, Dict, Any

class BaseDataLoader:
    def __init__(self, db_folder: str = "database"):
        self.db_folder = db_folder
        self.standards_df = None
        self.equipments_df = None
        
    def load_standards(self) -> List[Dict[str, Any]]:
        if self.standards_df is None:
            path = f"{self.db_folder}/标准库.xlsx"
            self.standards_df = pd.read_excel(path)
            # Fill NaN with empty string
            self.standards_df = self.standards_df.fillna("")
            
        return self.standards_df.to_dict('records')
        
    def load_equipments(self) -> List[Dict[str, Any]]:
        if self.equipments_df is None:
            path = f"{self.db_folder}/01-设备清单.xlsx"
            self.equipments_df = pd.read_excel(path) # Removed skiprows=1 because columns are on the first row
            self.equipments_df = self.equipments_df.fillna("")
            
        return self.equipments_df.to_dict('records')
