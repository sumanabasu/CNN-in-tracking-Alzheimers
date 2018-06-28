'''
Convolutional Neural Network
'''
import torch
import torch.nn as nn
from torch import FloatTensor

from  configurations.modelConfig import layer_config, params, num_classes

class CnnVanilla(nn.Module):
	"""Cnn with simple architecture of 6 stacked convolution layers followed by a fully connected layer"""
	
	def __init__(self):
		super(CnnVanilla, self).__init__()
		self.conv1 = nn.Conv3d(in_channels=layer_config['conv1']['in_channels'], out_channels=layer_config['conv1']['out_channels'],
							   kernel_size=layer_config['conv1']['kernel_size'], stride=layer_config['conv1']['stride'],
							   padding=layer_config['conv1']['padding'])
		self.conv2 = nn.Conv3d(in_channels=layer_config['conv2']['in_channels'], out_channels=layer_config['conv2']['out_channels'],
							   kernel_size=layer_config['conv2']['kernel_size'], stride=layer_config['conv2']['stride'],
							   padding=layer_config['conv2']['padding'])
		self.conv3 = nn.Conv3d(in_channels=layer_config['conv3']['in_channels'], out_channels=layer_config['conv3']['out_channels'],
							   kernel_size=layer_config['conv3']['kernel_size'], stride=layer_config['conv3']['stride'],
							   padding=layer_config['conv3']['padding'])
		self.conv4 = nn.Conv3d(in_channels=layer_config['conv4']['in_channels'], out_channels=layer_config['conv4']['out_channels'],
							   kernel_size=layer_config['conv4']['kernel_size'], stride=layer_config['conv4']['stride'],
							   padding=layer_config['conv4']['padding'])
		'''
		self.conv5 = nn.Conv3d(in_channels=layer_config['conv5']['in_channels'],
							   out_channels=layer_config['conv5']['out_channels'],
							   kernel_size=layer_config['conv5']['kernel_size'], stride=layer_config['conv5']['stride'],
							   padding=layer_config['conv5']['padding'])
		'''
		
		self.fc1 = nn.Linear(layer_config['fc1']['in'] , layer_config['fc1']['out'])
		self.fc21 = nn.Linear(layer_config['fc21']['in'], layer_config['fc21']['out'])
		self.fc22 = nn.Linear(layer_config['fc22']['in'], layer_config['fc22']['out'])
		
		self.bn1 = nn.BatchNorm3d(layer_config['conv1']['out_channels'])
		self.bn2 = nn.BatchNorm3d(layer_config['conv2']['out_channels'])
		self.bn3 = nn.BatchNorm3d(layer_config['conv3']['out_channels'])
		self.bn4 = nn.BatchNorm3d(layer_config['conv4']['out_channels'])
		# self.bn5 = nn.BatchNorm3d(layer_config['conv5']['out_channels'])
		
		self.dropout3d = nn.Dropout3d(p=params['model']['conv_drop_prob'])
		self.dropout = nn.Dropout(params['model']['fcc_drop_prob'])
		
		self.maxpool1 = nn.MaxPool3d(layer_config['maxpool3d']['l1']['kernel'], layer_config['maxpool3d'][
			'l1']['stride'])
		self.maxpool = nn.MaxPool3d(layer_config['maxpool3d']['ln']['kernel'], layer_config['maxpool3d'][
			'ln']['stride'])
		
		self.adaptiveMp3d = nn.AdaptiveMaxPool3d(layer_config['maxpool3d']['adaptive'])
		
		self.relu = nn.ReLU()
		self.logsoftmax1 = nn.LogSoftmax(dim=0)
		self.logsoftmax2 = nn.LogSoftmax(dim=0)
		
		#self.maxpool3d = nn.MaxPool3d(kernel_size=(3, 1, 1), stride=(3, 1, 1))
		
		for m in self.modules():
			if isinstance(m, nn.Conv3d):
				nn.init.kaiming_uniform(m.weight.data, mode='fan_in')
				#nn.init.kaiming_normal(m.weight.data, mode='fan_in')
				#nn.init.xavier_uniform(m.weight.data)
				nn.init.constant(m.bias.data, 0.01)
			elif isinstance(m, nn.Linear):
				nn.init.kaiming_uniform(m.weight.data, mode='fan_in')
				#nn.init.kaiming_normal(m.weight.data, mode='fan_in')
				#nn.init.xavier_uniform(m.weight.data)
				nn.init.constant(m.bias.data, 0.01)
			elif isinstance(m, nn.BatchNorm3d):
				nn.init.constant(m.weight.data, 1)
				nn.init.constant(m.bias.data, 0.01)
	
	def forward(self, x):
		#print(x.size())
		
		out1 = self.dropout3d(self.maxpool1(self.relu(self.bn1(self.conv1(x)))))
		#print(out1.size())
		
		out2 = self.dropout3d(self.maxpool(self.relu(self.bn2(self.conv2(out1)))))
		#print(out2.size())
		
		out3 = self.dropout3d(self.maxpool(self.relu(self.bn3(self.conv3(out2)))))
		#print(out3.size())
		
		out4 = self.dropout3d(self.maxpool(self.relu(self.bn4(self.conv4(out3)))))
		#print(out4.size())
	
		#out5 = self.dropout3d(self.maxpool(self.relu(self.bn5(self.conv5(out4)))))
		#print(out5.size())
		
		flat = out4.view(out4.size(0), -1)
		#print(flat.size())
		
		fcc1 = self.dropout(self.relu(self.fc1(flat)))
		fcc21 = self.fc21(fcc1)
		fcc22 = self.fc22(fcc1)
		#print(fcc1.size())
		
		# output = self.dropout(self.relu(self.fc2(fcc1)))
		# print(fcc2.size())
		
		log_softmax_nl_dis = self.logsoftmax1(fcc21)
		log_softmax_mci_ad = self.logsoftmax2(fcc22)
		
		
		output = torch.stack([log_softmax_nl_dis[:, 0], log_softmax_nl_dis[:, 1] + log_softmax_mci_ad[:, 0],
					   log_softmax_nl_dis[:, 1] +log_softmax_mci_ad[:, 1]])
		
		output = output.transpose(0, 1)
		
		#print(output.size())
		
		return output