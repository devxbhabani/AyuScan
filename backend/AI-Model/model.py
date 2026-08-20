import torch
import torch.nn as nn
import torch.nn.functional as F

class ECG1DCNN(nn.Module):
    def __init__(self, num_classes=4):
        super(ECG1DCNN, self).__init__()
        # Input shape: [Batch, 1, 1000] (for 10s at 100Hz)
        
        self.conv1 = nn.Conv1d(in_channels=1, out_channels=16, kernel_size=7, stride=1, padding=3)
        self.bn1 = nn.BatchNorm1d(16)
        self.pool1 = nn.MaxPool1d(kernel_size=2, stride=2) # 500
        
        self.conv2 = nn.Conv1d(in_channels=16, out_channels=32, kernel_size=5, stride=1, padding=2)
        self.bn2 = nn.BatchNorm1d(32)
        self.pool2 = nn.MaxPool1d(kernel_size=2, stride=2) # 250
        
        self.conv3 = nn.Conv1d(in_channels=32, out_channels=64, kernel_size=5, stride=1, padding=2)
        self.bn3 = nn.BatchNorm1d(64)
        self.pool3 = nn.MaxPool1d(kernel_size=2, stride=2) # 125
        
        self.conv4 = nn.Conv1d(in_channels=64, out_channels=128, kernel_size=3, stride=1, padding=1)
        self.bn4 = nn.BatchNorm1d(128)
        self.pool4 = nn.MaxPool1d(kernel_size=2, stride=2) # 62
        
        # Adaptive pooling to ensure consistent output size before fully connected layers
        self.adaptive_pool = nn.AdaptiveAvgPool1d(10)
        
        self.fc1 = nn.Linear(128 * 10, 256)
        self.dropout = nn.Dropout(0.5)
        self.fc2 = nn.Linear(256, num_classes)

    def forward(self, x):
        x = self.pool1(F.relu(self.bn1(self.conv1(x))))
        x = self.pool2(F.relu(self.bn2(self.conv2(x))))
        x = self.pool3(F.relu(self.bn3(self.conv3(x))))
        x = self.pool4(F.relu(self.bn4(self.conv4(x))))
        
        x = self.adaptive_pool(x)
        x = x.view(x.size(0), -1) # Flatten
        
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        x = self.fc2(x)
        return x

if __name__ == "__main__":
    # Test model shape
    model = ECG1DCNN()
    dummy_input = torch.randn(16, 1, 1000) # Batch of 16, 1 channel, 1000 length
    output = model(dummy_input)
    print("Output shape:", output.shape) # Should be [16, 4]
