import pickle
import json
from datetime import datetime
import os

class CheckpointManager:
    def __init__(self, checkpoint_dir="checkpoints"):
        self.checkpoint_dir = checkpoint_dir
        os.makedirs(checkpoint_dir, exist_ok=True)
    
    def save_checkpoint(self, state, node_name, checkpoint_id=None):
        if checkpoint_id is None:
            checkpoint_id = f"checkpoint_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        checkpoint_data = {
            'state': state,
            'current_node': node_name,
            'timestamp': datetime.now().isoformat(),
            'checkpoint_id': checkpoint_id
        }
        
        file_path = os.path.join(self.checkpoint_dir, f"{checkpoint_id}.pkl")
        with open(file_path, 'wb') as f:
            pickle.dump(checkpoint_data, f)
        
        return checkpoint_id
    
    def load_checkpoint(self, checkpoint_id):
        file_path = os.path.join(self.checkpoint_dir, f"{checkpoint_id}.pkl")
        try:
            with open(file_path, 'rb') as f:
                return pickle.load(f)
        except Exception:
            return None
        
    def list_checkpoints(self):
        return [f for f in os.listdir(self.checkpoint_dir) if f.endswith('.pkl')]