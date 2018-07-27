''''
train model
'''
import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F
from configurations.modelConfig import params, num_classes
from tqdm import tqdm
import numpy as np
from utils.visualizations import plot_confusion_matrix, plot_embedding
from utils.metrics import updateConfusionMatrix, calculateF1Score
from tensorboardX import SummaryWriter
from utils.save import saveModelandMetrics
from torch.optim.lr_scheduler import MultiStepLR
from data.splitDataset import getIndicesTrainValidTest
from utils.visualizations import plotROC

class Trainer(object):
	def __init__(self, model, train_loader, valid_loader, expt_folder):
		super(Trainer, self).__init__()
		
		if torch.cuda.is_available():
			self.model = model.cuda()
			
		self.train_loader = train_loader
		self.valid_loader = valid_loader
		self.optimizer = torch.optim.Adam(model.parameters(),
										  lr=params['train']['learning_rate'])
		self.reconstruction_loss = nn.CrossEntropyLoss()
		
		self.curr_epoch = 0
		self.batchstep = 0
		
		self.expt_folder = expt_folder
		self.writer = SummaryWriter(log_dir=expt_folder)
		
		self.train_losses_vae, self.train_ce, self.train_kld,\
		self.valid_losses, self.valid_ce, self.valid_kld, \
		self.train_f1_Score, self.valid_f1_Score, \
		self.train_accuracy, self.valid_accuracy = ([] for i in range(10))
		
		self.trainset_size, self.validset_size, self.testset_size = getIndicesTrainValidTest(requireslen=True)
	
	def klDivergence(self, mu, logvar):
		# TODO : update KL Divergence between posterior distribution and prior distribution
		# D_KL(Q(z|X) || P(z|X))
		# P(z|X) is the real distribution, Q(z|X) is the distribution we are trying to approximate P(z|X) with
		# calculate in closed form
		return (-0.5 * torch.mean(1 + logvar - mu.pow(2) - logvar.exp()))
		
		#self.lambda_ = 1	#hyper-parameter to control regularizer by reconstruction loss
	def vae_loss(self, recon_y, y, mu, logvar):
		CE = self.reconstruction_loss(recon_y, y)
		#MSE = nn.CrossEntropyLoss(recon_x, x, size_average=False)
		# BCE = F.mse_loss(recon_x, x, size_average=False)
		
		KLD = self.klDivergence(mu, logvar)
		
		return CE + KLD, CE, KLD
	
	def train(self):
		scheduler = MultiStepLR(self.optimizer, milestones=params['train']['lr_schedule'], gamma=0.1)	# [40,
		# 60] earlier
		
		for _ in range(params['train']['num_epochs']):
			print('Training...\nEpoch : '+str(self.curr_epoch))
			scheduler.step()
			
			# Train Model
			accuracy, vae_loss, ce, kld, f1_score = self.trainEpoch()
			
			self.train_losses_vae.append(vae_loss)
			self.train_ce.append(ce)
			self.train_kld.append(kld)
			self.train_accuracy.append(accuracy)
			self.train_f1_Score.append(f1_score)
			
			# Validate Model
			print ('Validation...')
			self.validate()
			
			# Save model
			saveModelandMetrics(self)
			
			# TODO : Stop learning if model doesn't improve for 10 epochs --> Save best model
			
			self.curr_epoch += 1
	
	def trainEpoch(self):
		self.model.train(True)
		
		pbt = tqdm(total=len(self.train_loader))
		
		cm = np.zeros((num_classes, num_classes), int)
		
		minibatch_losses_vae = 0
		minibatch_accuracy = 0
		minibatch_kld = 0
		minibatch_ce = 0
		
		for batch_idx, (images, labels) in enumerate(self.train_loader):
			
			torch.cuda.empty_cache()
			accuracy, conf_mat, vae_loss, kld, ce = self.trainBatch(batch_idx, images, labels)
			
			minibatch_losses_vae += vae_loss
			minibatch_kld += kld
			minibatch_ce += ce
			minibatch_accuracy += accuracy
			cm += conf_mat
			
			pbt.update(1)
		
		pbt.close()
		
		minibatch_losses_vae /= self.trainset_size
		minibatch_ce /= self.trainset_size
		minibatch_kld /= self.trainset_size
		minibatch_accuracy /= self.trainset_size
		
		# Plot losses
		self.writer.add_scalar('train_vae_loss', minibatch_losses_vae, self.curr_epoch)
		self.writer.add_scalar('train_reconstruction_loss', minibatch_ce, self.curr_epoch)
		self.writer.add_scalar('train_KL_divergence', minibatch_kld, self.curr_epoch)
		self.writer.add_scalar('train_accuracy', minibatch_accuracy, self.curr_epoch)
		
		# Plot confusion matrices
		plot_confusion_matrix(cm, location=self.expt_folder, title='Confusion matrix, ' \
																			  '(Train)')
		
		# F1 Score
		f1_score = calculateF1Score(cm)
		self.writer.add_scalar('train_f1_score', f1_score, self.curr_epoch)
		print('F1 Score : ', f1_score)
		
		# plot ROC curve
		#plotROC(cm, location=self.expt_folder, title='ROC Curve(Train)')
		
		return minibatch_accuracy, minibatch_losses_vae, minibatch_ce, minibatch_kld, f1_score
	
	def trainBatch(self, batch_idx, images, labels):
		images = Variable(images).cuda()
		labels = Variable(labels).cuda()
		labels = labels.view(-1, )
		
		# Forward + Backward + Optimize
		
		# y_hat is generated label
		pred_labels, mu, logvar = self.model(images, labels)
		loss, ce, kld = self.vae_loss(pred_labels, labels, mu, logvar)
		
		self.optimizer.zero_grad()
		#classification_loss.backward(retain_graph=True)
		loss.backward()
		
		
		self.optimizer.step()
		
		# Compute accuracy
		accuracy = (labels == pred_labels).float().sum()
		
		# Print metrics
		if batch_idx % 100 == 0:
			print('Epoch [%d/%d], Batch [%d/%d] VAE Loss: %.4f Accuracy: %0.2f '
				  % (self.curr_epoch, params['train']['num_epochs'],
					 batch_idx, self.trainset_size,
					 loss.data[0],
					 accuracy * 1.0 / params['train']['batch_size']))
			
		cm = updateConfusionMatrix(labels.data.cpu().numpy(), pred_labels.data.cpu().numpy())
		
		# clean GPU
		del images, labels, pred_labels, mu, logvar
		
		self.writer.add_scalar('minibatch_vae_loss', np.mean(loss.data[0]), self.batchstep)
		self.batchstep += 1
		
		return accuracy, cm, loss.data[0], kld.data[0], ce.data[0]
	
	def validate(self):
		self.model.eval()
		correct = 0
		mse = 0
		kld = 0
		cm = np.zeros((num_classes, num_classes), int)
		loss = 0
		
		pb = tqdm(total=len(self.valid_loader))
		
		for i, (images, labels) in enumerate(self.valid_loader):
			img = Variable(images, volatile=True).cuda()
			_, _, mu, logvar, x_hat, p_hat = self.model(img)
			_, predicted = torch.max(p_hat.data, 1)
			labels = labels.view(-1, )
			correct += ((predicted.cpu() == labels).float().sum())
			
			cm += updateConfusionMatrix(labels.numpy(), predicted.cpu().numpy())
			
			loss += self.classification_criterion(p_hat, Variable(labels).cuda()).data
			mse += self.reconstruction_loss(x_hat, img).data
			kld += self.klDivergence(mu, logvar).data
			
			del img, x_hat, p_hat, _, predicted, mu, logvar
			pb.update(1)
			
		pb.close()
		
		correct /= self.validset_size
		mse /= self.validset_size
		kld /= self.validset_size
		loss /= self.validset_size
		
		print('Validation Accuracy : %0.6f' % correct)
		
		self.valid_accuracy.append(correct)
		self.valid_mse.append(mse)
		self.valid_kld.append(kld)
		self.valid_losses.append(loss)
		
		# Plot loss and accuracy
		self.writer.add_scalar('validation_accuracy', correct, self.curr_epoch)
		self.writer.add_scalar('validation_loss', loss * 1.0 / self.validset_size, self.curr_epoch)
		self.writer.add_scalar('validation_mse', mse , self.curr_epoch)
		self.writer.add_scalar('validation KLD', kld , self.curr_epoch)
		#print('MSE : ', mse)
		#print('KLD : ', kld)
		
		# Plot confusion matrices
		plot_confusion_matrix(cm, location=self.expt_folder, title='Confusion matrix, ' \
																			  'without normalization (Valid)')
		
		# F1 Score
		f1_score = calculateF1Score(cm)
		self.writer.add_scalar('valid_f1_score', f1_score, self.curr_epoch)
		print('F1 Score : ', calculateF1Score(cm))
		self.valid_f1_Score.append(f1_score)
		
		# plot ROC curve
		#plotROC(cm, location=self.expt_folder, title='ROC Curve(Valid)')
	
	def test(self, test_loader):
		self.model.eval()
		print ('Test...')
		
		correct =0
		test_losses = 0
		cm = np.zeros((num_classes, num_classes), int)
		
		encoder_embedding = []
		classifier_embedding = []
		pred_labels = []
		act_labels = []
		
		pb = tqdm(total=len(self.valid_loader))
		
		for i, (images, labels) in enumerate(test_loader):
			img = Variable(images, volatile=True).cuda()
			enc_emb, cls_emb, _, _, _, p_hat = self.model(img)
			_, predicted = torch.max(p_hat.data, 1)
			labels = labels.view(-1, )
			correct += ((predicted.cpu() == labels).float().sum())
			
			cm += updateConfusionMatrix(labels.numpy(), predicted.cpu().numpy())
			
			loss = self.classification_criterion(p_hat, Variable(labels).cuda())
			test_losses += loss.data[0]
			
			del img
			pb.update(1)
			
			encoder_embedding.extend(np.array(enc_emb))
			classifier_embedding.extend(np.array(cls_emb))
			pred_labels.extend(np.array(predicted.cpu().numpy()))
			act_labels.extend(np.array(labels.numpy()))
		
		pb.close()
		
		correct /= self.testset_size
		test_losses /= self.testset_size
		
		print('Test Accuracy : %0.6f' % correct)
		print('Test Losses : %0.6f' % test_losses)
		
		# Plot confusion matrices
		plot_confusion_matrix(cm, location=self.expt_folder, title='Confusion matrix, ' \
																			  'without normalization (Test)')
		
		# F1 Score
		print('F1 Score : ', calculateF1Score(cm))
		
		# plot PCA or tSNE
		encoder_embedding = np.array(encoder_embedding)
		classifier_embedding = np.array(classifier_embedding)
		pred_labels = np.array(pred_labels)
		act_labels = np.array(act_labels)
		
		plot_embedding(encoder_embedding, act_labels, pred_labels, mode='tsne', location=self.expt_folder,
					   title='encoder_embedding_test')
		plot_embedding(encoder_embedding, act_labels, pred_labels, mode='pca', location=self.expt_folder,
					   title='encoder_embedding_test')
		
		
		plot_embedding(classifier_embedding, act_labels, pred_labels, mode='tsne', location=self.expt_folder,
					   title='classifier_embedding_test')
		plot_embedding(classifier_embedding, act_labels, pred_labels, mode='pca', location=self.expt_folder,
					   title='classifier_embedding_test')
		
		# plot ROC curve
		#plotROC(cm, location=self.expt_folder, title='ROC Curve(Test)')
		