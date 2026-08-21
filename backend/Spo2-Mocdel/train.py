import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix
import time

# --- 1. Model Definitions ---
class SpO2_GRU(nn.Module):
    def __init__(self, input_size=1, hidden_size=16, num_layers=1, num_classes=4):
        super(SpO2_GRU, self).__init__()
        self.gru = nn.GRU(input_size, hidden_size, num_layers, batch_first=True)
        self.fc = nn.Linear(hidden_size, num_classes)
        
    def forward(self, x):
        # x shape: [batch, seq_len, features]
        out, _ = self.gru(x)
        # Take the output of the last time step
        out = self.fc(out[:, -1, :])
        return out

class SpO2_CNN(nn.Module):
    def __init__(self, num_classes=4):
        super(SpO2_CNN, self).__init__()
        self.conv1 = nn.Conv1d(in_channels=1, out_channels=16, kernel_size=3, padding=1)
        self.relu = nn.ReLU()
        self.pool = nn.MaxPool1d(2)
        self.conv2 = nn.Conv1d(in_channels=16, out_channels=32, kernel_size=3, padding=1)
        self.fc1 = nn.Linear(32 * 15, 32) # Assuming seq_len=60, pooled twice = 15
        self.fc2 = nn.Linear(32, num_classes)

    def forward(self, x):
        # x shape: [batch, seq_len, features] -> [batch, features, seq_len] for CNN
        x = x.transpose(1, 2)
        x = self.pool(self.relu(self.conv1(x)))
        x = self.pool(self.relu(self.conv2(x)))
        x = x.view(x.size(0), -1)
        x = self.relu(self.fc1(x))
        x = self.fc2(x)
        return x

def train_model():
    print("Loading dataset...")
    data = np.load("spo2_dataset.npz")
    X = data['X'].astype(np.float32)
    y = data['y'].astype(np.int64)
    
    # Normalize X (SpO2 values usually 70-100)
    X = (X - 90.0) / 10.0

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    train_dataset = TensorDataset(torch.tensor(X_train), torch.tensor(y_train))
    test_dataset = TensorDataset(torch.tensor(X_test), torch.tensor(y_test))
    
    train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=32, shuffle=False)
    
    # Select Model (GRU is best for temporal trends)
    print("Initializing GRU model...")
    model = SpO2_GRU()
    
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    
    epochs = 20
    best_loss = float('inf')
    
    print("Training started...")
    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for inputs, labels in train_loader:
            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * inputs.size(0)
            
        train_loss /= len(train_loader.dataset)
        
        # Validation
        model.eval()
        val_loss = 0.0
        correct = 0
        total = 0
        with torch.no_grad():
            for inputs, labels in test_loader:
                outputs = model(inputs)
                loss = criterion(outputs, labels)
                val_loss += loss.item() * inputs.size(0)
                _, predicted = torch.max(outputs.data, 1)
                total += labels.size(0)
                correct += (predicted == labels).sum().item()
                
        val_loss /= len(test_loader.dataset)
        accuracy = 100 * correct / total
        
        print(f"Epoch {epoch+1}/{epochs} | Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f} | Val Acc: {accuracy:.2f}%")
        
        if val_loss < best_loss:
            best_loss = val_loss
            torch.save(model.state_dict(), "spo2_model.pth")
            
    print("Training complete. Best model saved as spo2_model.pth.")
    
    # Evaluation
    model.load_state_dict(torch.load("spo2_model.pth"))
    model.eval()
    y_pred = []
    y_true = []
    
    start_time = time.time()
    with torch.no_grad():
        for inputs, labels in test_loader:
            outputs = model(inputs)
            _, predicted = torch.max(outputs, 1)
            y_pred.extend(predicted.numpy())
            y_true.extend(labels.numpy())
    inference_time = (time.time() - start_time) / len(test_dataset)
            
    print(f"\nAverage Inference Speed (CPU): {inference_time*1000:.2f} ms per sample")
    
    print("\nClassification Report:")
    print(classification_report(y_true, y_pred, target_names=["Stable", "Mild Decline", "Rapid Decline", "Critical"]))
    print("Confusion Matrix:")
    print(confusion_matrix(y_true, y_pred))

if __name__ == "__main__":
    train_model()
