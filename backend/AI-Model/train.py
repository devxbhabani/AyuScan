import torch
import torch.nn as nn
import torch.optim as optim
from dataset_loader import get_dataloaders
from model import ECG1DCNN
import os

def train_model(dataset_path, num_epochs=5, batch_size=64, learning_rate=0.001):
    # Set device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    # Get data loaders
    print("Preparing datasets...")
    train_loader, val_loader = get_dataloaders(dataset_path, batch_size=batch_size, train_split=0.8)
    
    # Initialize model, loss, optimizer
    model = ECG1DCNN(num_classes=4).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=learning_rate)
    
    best_val_loss = float('inf')
    model_save_path = os.path.join(dataset_path, '..', 'ecg_model.pth')

    for epoch in range(num_epochs):
        print(f"\n--- Epoch {epoch+1}/{num_epochs} ---")
        
        # Training Phase
        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0
        
        for i, (inputs, labels) in enumerate(train_loader):
            inputs, labels = inputs.to(device), labels.to(device)
            
            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            
            train_loss += loss.item() * inputs.size(0)
            _, predicted = torch.max(outputs.data, 1)
            train_total += labels.size(0)
            train_correct += (predicted == labels).sum().item()
            
            if (i+1) % 50 == 0:
                print(f"  Step [{i+1}/{len(train_loader)}], Loss: {loss.item():.4f}")
                
        epoch_train_loss = train_loss / train_total
        epoch_train_acc = 100 * train_correct / train_total
        
        # Validation Phase
        model.eval()
        val_loss = 0.0
        val_correct = 0
        val_total = 0
        
        with torch.no_grad():
            for inputs, labels in val_loader:
                inputs, labels = inputs.to(device), labels.to(device)
                outputs = model(inputs)
                loss = criterion(outputs, labels)
                
                val_loss += loss.item() * inputs.size(0)
                _, predicted = torch.max(outputs.data, 1)
                val_total += labels.size(0)
                val_correct += (predicted == labels).sum().item()
                
        epoch_val_loss = val_loss / val_total
        epoch_val_acc = 100 * val_correct / val_total
        
        print(f"Train Loss: {epoch_train_loss:.4f}, Train Acc: {epoch_train_acc:.2f}%")
        print(f"Val Loss: {epoch_val_loss:.4f}, Val Acc: {epoch_val_acc:.2f}%")
        
        # Save best model
        if epoch_val_loss < best_val_loss:
            best_val_loss = epoch_val_loss
            print(f"Validation loss decreased. Saving model to {model_save_path}")
            torch.save(model.state_dict(), model_save_path)

    print("\nTraining complete.")

if __name__ == "__main__":
    DATASET_PATH = "d:/AyuScan/backend/AI-model/dataset"
    # Using a small number of epochs (3) for a fast prototype.
    train_model(DATASET_PATH, num_epochs=5, batch_size=64)
