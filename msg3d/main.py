#!/usr/bin/env python
from __future__ import print_function
import os
import time
import yaml
import pprint
import random
import pickle
import shutil
import inspect
import argparse
from collections import OrderedDict, defaultdict

import torch
import numpy as np
import torch.nn as nn
import torch.optim as optim
from tqdm import tqdm
from tensorboardX import SummaryWriter
from torch.optim.lr_scheduler import MultiStepLR, ReduceLROnPlateau, CosineAnnealingLR
import apex

from utils import count_params, import_class



def init_seed(arg, worker_id = 0):
    seed = arg.seed + worker_id
    torch.cuda.manual_seed_all(seed)
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)
    if (arg.use_deterministic):
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def get_parser():
    # parameter priority: command line > config file > default
    parser = argparse.ArgumentParser(description='MS-G3D')

    parser.add_argument(
        '--work-dir',
        type=str,
        required=True,
        help='the work folder for storing results')
    parser.add_argument(
        '--dataset',
        type=str,
        required=True,
        help='Dataset used')
    parser.add_argument(
        '--stream',
        type=str,
        required=True,
        help='Stream used')
    parser.add_argument(
        '--num-classes',
        type=int,
        required=True,
        help='Stream used')

    parser.add_argument('--model_saved_name', default='')
    parser.add_argument(
        '--config',
        default='/home/bdd/LSE_Lex40_uvigo/dataconfig/nturgbd-cross-view/test_bone.yaml',
        help='path to the configuration file')
    parser.add_argument(
        '--assume-yes',
        action='store_true',
        help='Say yes to every prompt')

    parser.add_argument(
        '--phase',
        default='train',
        help='must be train or test')
    parser.add_argument(
        '--save-score',
        type=str2bool,
        default=False,
        help='if ture, the classification score will be stored')

    parser.add_argument(
        '--seed',
        type=int,
        default=random.randrange(200),
        help='random seed')
    parser.add_argument(
        '--log-interval',
        type=int,
        default=100,
        help='the interval for printing messages (#iteration)')
    parser.add_argument(
        '--save-interval',
        type=int,
        default=1,
        help='the interval for storing models (#iteration)')
    parser.add_argument(
        '--eval-interval',
        type=int,
        default=1,
        help='the interval for evaluating models (#iteration)')
    parser.add_argument(
        '--eval-start',
        type=int,
        default=1,
        help='The epoch number to start evaluating models')
    parser.add_argument(
        '--print-log',
        type=str2bool,
        default=True,
        help='print logging or not')
    parser.add_argument(
        '--show-topk',
        type=int,
        default=[1, 5],
        nargs='+',
        help='which Top K accuracy will be shown')

    parser.add_argument(
        '--feeder',
        default='feeder.feeder',
        help='data loader will be used')
    parser.add_argument(
        '--num-worker',
        type=int,
        default=os.cpu_count(),
        help='the number of worker for data loader')
    parser.add_argument(
        '--train-feeder-args',
        default=dict(),
        help='the arguments of data loader for training')
    parser.add_argument(
        '--test-feeder-args',
        default=dict(),
        help='the arguments of data loader for test')

    parser.add_argument(
        '--model',
        default=None,
        help='the model will be used')
    parser.add_argument(
        '--model-args',
        type=dict,
        default=dict(),
        help='the arguments of model')
    parser.add_argument(
        '--weights',
        default=None,
        help='the weights for network initialization')
    parser.add_argument(
        '--ignore-weights',
        type=str,
        default=[],
        nargs='+',
        help='the name of weights which will be ignored in the initialization')
    parser.add_argument(
        '--half',
        action='store_true',
        help='Use half-precision (FP16) training')
    parser.add_argument(
        '--amp-opt-level',
        type=int,
        default=1,
        help='NVIDIA Apex AMP optimization level')

    parser.add_argument(
        '--base-lr',
        type=float,
        default=0.01,
        help='initial learning rate')
    parser.add_argument(
        '--step',
        type=int,
        default=[20, 40, 60],
        nargs='+',
        help='the epoch where optimizer reduce the learning rate')
    parser.add_argument(
        '--device',
        type=int,
        default=0,
        nargs='+',
        help='the indexes of GPUs for training or testing')
    parser.add_argument(
        '--optimizer',
        default='SGD',
        help='type of optimizer')
    parser.add_argument(
        '--nesterov',
        type=str2bool,
        default=False,
        help='use nesterov or not')
    parser.add_argument(
        '--batch-size',
        type=int,
        default=32,
        help='training batch size')
    parser.add_argument(
        '--test-batch-size',
        type=int,
        default=256,
        help='test batch size')
    parser.add_argument(
        '--forward-batch-size',
        type=int,
        default=16,
        help='Batch size during forward pass, must be factor of --batch-size')
    parser.add_argument(
        '--start-epoch',
        type=int,
        default=0,
        help='start training from which epoch')
    parser.add_argument(
        '--num-epoch',
        type=int,
        default=80,
        help='stop training in which epoch')
    parser.add_argument(
        '--weight-decay',
        type=float,
        default=0.0005,
        help='weight decay for optimizer')
    parser.add_argument(
        '--optimizer-states',
        type=str,
        help='path of previously saved optimizer states')
    parser.add_argument(
        '--checkpoint',
        type=str,
        help='path of previously saved training checkpoint')
    parser.add_argument(
        '--debug',
        type=str2bool,
        default=False,
        help='Debug mode; default false')
    
    parser.add_argument(
        '--use-tta',
        help='Activate tta - deactived use only first element in the config file',
        action='store_true')

    parser.add_argument(
        '--tta',
        default=[[False, 1]],
        help='Config tta')
    
    parser.add_argument(
        '--lr-scheduler',
        default='MultiStepLR',
        help='type of LR scheduler')
    
    parser.add_argument(
        '--gamma',
        type=float,
        default=0.1,
        help='Gamma paremeter MultiStepLR')

    parser.add_argument(
        '--factor',
        type=float,
        default=0.1,
        help='Factor paremeter ReduceLROnPlateau')

    parser.add_argument(
        '--patience',
        type=int,
        default=10,
        help='Patience paremeter ReduceLROnPlateau')
    
    parser.add_argument(
        '--cooldown',
        type=int,
        default=0,
        help='Cooldown parameter ReduceLROnPlateau')

    parser.add_argument(
        '--tmax',
        type=int,
        default=0,
        help='tmax parameter CosineAnnealingLR')

    parser.add_argument(
        '--eta-min',
        type=float,
        default=0.0001,
        help='eta_min parameter CosineAnnealingLR')

    parser.add_argument(
        '--epoch-warn',
        type=int,
        default=0,
        help='Epoch without scheduler steps')

    parser.add_argument(
        '--early-stopping',
        type=int,
        default=0,
        help='stop training if not improve in X epochs')
    
    parser.add_argument(
        '--use-deterministic',
        help='Activate deterministic characteristic',
        action='store_true')

    parser.add_argument(
        '--use-normalization',
        help='Activate normalization',
        action='store_true')

    parser.add_argument(
        '--use-train-normalization',
        type=str,
        default=None,
        help='Use normalized data and provide the folder where this data is located')

    parser.add_argument(
        '--dhf',
        type=float,
        default=0,
        help='Nivel de drophand fixed')

    parser.add_argument(
        '--dhw',
        type=float,
        default=0,
        help='Nivel de drophand weighted respect to the visibility')

    return parser


class Processor():
    """Processor for Skeleton-based Action Recgnition"""

    def __init__(self, arg):
        self.arg = arg
        self.save_arg()
        if arg.phase == 'train':
            # Added control through the command line
            arg.train_feeder_args['debug'] = arg.train_feeder_args['debug'] or self.arg.debug
            logdir = os.path.join(arg.work_dir, 'trainlogs')
            if not arg.train_feeder_args['debug']:
                # logdir = arg.model_saved_name
                if os.path.isdir(logdir):
                    print(f'log_dir {logdir} already exists')
                    if arg.assume_yes:
                        answer = 'y'
                    else:
                        answer = input('delete it? [y]/n:')
                    if answer.lower() in ('y', ''):
                        shutil.rmtree(logdir)
                        print('Dir removed:', logdir)
                    else:
                        print('Dir not removed:', logdir)

                self.train_writer = SummaryWriter(os.path.join(logdir, 'train'), 'train')
                self.val_writer = SummaryWriter(os.path.join(logdir, 'val'), 'val')
            else:
                self.train_writer = SummaryWriter(os.path.join(logdir, 'debug'), 'debug')
                
        self.lst_name_test_tta=[]
        self.get_lst_name_test_tta()
        self.print_log('USE TTA:',len(self.lst_name_test_tta))
        for idx, name_test_tta in enumerate(self.lst_name_test_tta):
            self.print_log('tta {}: {} > {}'.format(idx, name_test_tta, self.arg.tta[idx]))

        self.load_model()
        self.load_param_groups()
        self.load_optimizer()
        self.load_lr_scheduler()
        self.load_data()

        self.global_step = 0
        self.lr = self.arg.base_lr
        self.best_acc = 0
        self.best_acc_epoch = 0
        self.best_loss_val = -1
        self.counter_early_stopping = 0

        if self.arg.half:
            self.print_log('*************************************')
            self.print_log('*** Using Half Precision Training ***')
            self.print_log('*************************************')
            self.model, self.optimizer = apex.amp.initialize(
                self.model,
                self.optimizer,
                opt_level=f'O{self.arg.amp_opt_level}'
            )
            if self.arg.amp_opt_level != 1:
                self.print_log('[WARN] nn.DataParallel is not yet supported by amp_opt_level != "O1"')

        if type(self.arg.device) is list:
            if len(self.arg.device) > 1:
                self.print_log(f'{len(self.arg.device)} GPUs available, using DataParallel')
                self.model = nn.DataParallel(
                    self.model,
                    device_ids=self.arg.device,
                    output_device=self.output_device
                )

    def load_model(self):
        output_device = self.arg.device[0] if type(self.arg.device) is list else self.arg.device
        self.output_device = output_device
        Model = import_class(self.arg.model)

        # Copiar archivos del modelo y el script principal
        shutil.copy2(inspect.getfile(Model), self.arg.work_dir)
        shutil.copy2(os.path.join('.', __file__), self.arg.work_dir)

        # Inicializar el modelo
        self.model = Model(**self.arg.model_args).cuda(output_device)
        self.loss = nn.CrossEntropyLoss().cuda(output_device)

        # Modificar la capa de salida del modelo según el número de clases
        if hasattr(self.model, 'fc'):
            in_features = self.model.fc.in_features
            self.model.fc = nn.Linear(in_features, self.arg.num_classes).cuda(self.output_device)
        elif hasattr(self.model, 'classifier'):
            in_features = self.model.classifier.in_features
            self.model.classifier = nn.Linear(in_features, self.arg.num_classes).cuda(self.output_device)

        self.print_log(f'Model total number of params: {count_params(self.model)}')

        # Si se proporcionan pesos, cargarlos
        if self.arg.weights:
            try:
                # Intentar extraer el global_step desde el nombre del archivo de pesos
                self.global_step = int(self.arg.weights[:-3].split('-')[-1])
            except:
                self.print_log('Cannot parse global_step from model weights filename')
                self.global_step = 0

            self.print_log(f'Loading weights from {self.arg.weights}')
            
            # Cargar los pesos de acuerdo con el tipo de archivo (pkl o pt)
            if '.pkl' in self.arg.weights:
                with open(self.arg.weights, 'r') as f:
                    weights = pickle.load(f)
            else:
                weights = torch.load(self.arg.weights)

            # Mover los pesos a la GPU
            weights = OrderedDict(
                [[k.split('module.')[-1], v.cuda(output_device)] for k, v in weights.items()])

            # Eliminar pesos que no son necesarios
            for w in self.arg.ignore_weights:
                if weights.pop(w, None) is not None:
                    self.print_log(f'Successfully removed weight: {w}')
                else:
                    self.print_log(f'Cannot remove weight: {w}')

  
            # Intentar cargar los pesos en el modelo, con una carga parcial si es necesario
            try:
                
           
                self.model.load_state_dict(weights, strict=False)

                # Congelar todas las capas excepto la última
               

            except Exception as e:
                # Si hay un error de desajuste de tamaños, actualizar el estado del modelo parcialmente
                self.print_log(f"Error loading weights: {e}")
                state = self.model.state_dict()
                diff = list(set(state.keys()).difference(set(weights.keys())))
                self.print_log('Cannot find these weights:')
                for d in diff:
                    self.print_log('  ' + d)
                state.update(weights)  # Actualizar el estado del modelo con los pesos disponibles
                self.model.load_state_dict(state)
                self.print_log("Weights loaded partially. Some layers were ignored due to shape mismatch.")

    def load_param_groups(self):
        """
        Template function for setting different learning behaviour
        (e.g. LR, weight decay) of different groups of parameters
        """
        self.param_groups = defaultdict(list)

        for name, params in self.model.named_parameters():
            self.param_groups['other'].append(params)

        self.optim_param_groups = {
            'other': {'params': self.param_groups['other']}
        }

    def load_optimizer(self):
        params = list(self.optim_param_groups.values())      
        if self.arg.optimizer == 'SGD':
            self.optimizer = optim.SGD(
                params,
                lr=self.arg.base_lr,
                momentum=0.9,
                nesterov=self.arg.nesterov,
                weight_decay=self.arg.weight_decay)
        elif self.arg.optimizer == 'Adam':
            self.optimizer = optim.Adam(
                params,
                lr=self.arg.base_lr,
                weight_decay=self.arg.weight_decay)
        else:
            raise ValueError('Unsupported optimizer: {}'.format(self.arg.optimizer))

        # Load optimizer states if any
        if self.arg.checkpoint is not None:
            self.print_log(f'Loading optimizer states from: {self.arg.checkpoint}')
            self.optimizer.load_state_dict(torch.load(self.arg.checkpoint)['optimizer_states'])
            current_lr = self.optimizer.param_groups[0]['lr']
            self.print_log(f'Starting LR: {current_lr}')
            self.print_log(f'Starting WD1: {self.optimizer.param_groups[0]["weight_decay"]}')
            if len(self.optimizer.param_groups) >= 2:
                self.print_log(f'Starting WD2: {self.optimizer.param_groups[1]["weight_decay"]}')

    def load_lr_scheduler(self):

        self.print_log(f'Loading lr scheduler: {self.arg.lr_scheduler}')

        self.lr_scheduler = None
        if self.arg.lr_scheduler == "MultiStepLR":
            self.lr_scheduler = MultiStepLR(self.optimizer, milestones=self.arg.step, gamma=self.arg.gamma)
            self.print_log(f'Activated MultiStepLR gamma : {self.arg.gamma}')

        if self.arg.lr_scheduler == "ReduceLROnPlateau":
            self.print_log(f'Activated ReduceLROnPlateau - factor : {self.arg.factor} - patience: {self.arg.patience} - cooldown: {self.arg.cooldown}')
            self.lr_scheduler =  ReduceLROnPlateau(
                self.optimizer,
                mode = 'min',
                factor = self.arg.factor,
                patience=self.arg.patience,
                threshold=0.0001,
                threshold_mode='rel', 
                cooldown=self.arg.cooldown,
                min_lr=1e-06,   
                eps=1e-08
            )

        if self.arg.lr_scheduler == "CosineAnnealingLR":
            self.print_log(f'Activated CosineAnnealingLR - Tmax : {self.arg.tmax} - eta_min: {self.arg.eta_min} - epoch_warn: {self.arg.epoch_warn}')
            self.lr_scheduler = CosineAnnealingLR(
                self.optimizer, 
                T_max=self.arg.tmax,
                eta_min=self.arg.eta_min
            )
            
        if self.arg.checkpoint is not None:
            scheduler_states = torch.load(self.arg.checkpoint)['lr_scheduler_states']
            self.print_log(f'Loading LR scheduler states from: {self.arg.checkpoint}')
            self.lr_scheduler.load_state_dict(scheduler_states)
            self.print_log(f'Starting last epoch: {scheduler_states["last_epoch"]}')
            self.print_log(f'Loaded milestones: {scheduler_states["last_epoch"]}')

    def load_data(self):
        Feeder = import_class(self.arg.feeder)
        self.data_loader = dict()

        def worker_seed_fn(worker_id):
            # give workers different seeds
            return init_seed(self.arg, worker_id=worker_id)
        
        if (self.arg.dhf > 0):
            self.print_log(f'drophand [DHF]: Activated')
        else:
            self.print_log(f'drophand [DHF]: Deactivated')

        if (self.arg.dhw > 0):
            self.print_log(f'drophand [DHW]: Activated')
        else:
            self.print_log(f'drophand [DHF]: Deactivated')

        # print('*************************************')
        # print('LOAD DATA')
        # print('*************************************')

        if self.arg.phase == 'train':
            train_feeder = Feeder(**self.arg.train_feeder_args, random_flip=True, dhf=self.arg.dhf, dhw=self.arg.dhw, random_resizer=False, use_normalization=self.arg.use_normalization)
            
            if self.arg.use_train_normalization != None:
                train_mean = train_feeder.get_calculated_mean()
                train_std = train_feeder.get_calculated_std()
                filepath_out_mean = os.path.join(self.arg.use_train_normalization, 'train_mean.npy')
                filepath_out_std = os.path.join(self.arg.use_train_normalization, 'train_std.npy')
                np.save(filepath_out_mean, train_mean)
                np.save(filepath_out_std, train_std)

                self.print_log("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
                self.print_log("'TRAIN_MEAN_FEEDER - SHAPE', train_mean.shape - saved in: " + filepath_out_mean)
                self.print_log("'TRAIN_STD_FEEDER - SHAPE', train_std.shape - saved in: " + filepath_out_std)
                self.print_log("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
            else:
                self.print_log("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
                self.print_log("NO CALCULATED MEAN STD TRAIN FEEDER")
                self.print_log("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")

            self.data_loader['train'] = torch.utils.data.DataLoader(
                dataset=train_feeder,
                batch_size=self.arg.batch_size,
                shuffle=True,
                generator=torch.Generator().manual_seed(self.arg.seed),
                num_workers=self.arg.num_worker,
                drop_last=True,
                pin_memory=True,
                worker_init_fn=worker_seed_fn)
                
        for idx, name_test_tta in enumerate(self.lst_name_test_tta):
            self.print_log('Load dataset: {}'.format(name_test_tta))
            mean_normalization = None
            std_normalization = None
            if (self.arg.use_train_normalization != None):
                self.print_log("Test feeder - read train normalization data")
                mean_normalization = np.load(os.path.join(self.arg.use_train_normalization,'train_mean.npy'))
                std_normalization = np.load(os.path.join(self.arg.use_train_normalization,'train_std.npy'))

            self.data_loader[name_test_tta] = torch.utils.data.DataLoader(

                dataset=Feeder(**self.arg.test_feeder_args, random_flip=False, dhf=0, dhw=0, random_resizer=False, tta=self.arg.tta[idx], use_normalization=self.arg.use_normalization, mean=mean_normalization, std=std_normalization),
                
                # dataset=Feeder(**self.arg.test_feeder_args, random_flip=False, drophand=0, random_resizer=False, tta=self.arg.tta[idx]),

                #dataset=Feeder(**self.arg.test_feeder_args, random_flip=False, drophand=0, random_resizer=False),
                batch_size=self.arg.test_batch_size,
                shuffle=False,
                generator=torch.Generator().manual_seed(self.arg.seed),
                num_workers=self.arg.num_worker,
                drop_last=False,
                pin_memory = True,
                worker_init_fn=worker_seed_fn)
    
    def get_lst_name_test_tta(self):
        for idx, tta_params in enumerate(self.arg.tta):
            name_test_tta = 'test_tta_'+str(idx)
            self.lst_name_test_tta.append(name_test_tta)

    def save_arg(self):
        # save arg
        arg_dict = vars(self.arg)
        if not os.path.exists(self.arg.work_dir):
            os.makedirs(self.arg.work_dir)
        with open(os.path.join(self.arg.work_dir, 'config.yaml'), 'w') as f:
            yaml.dump(arg_dict, f)

    def print_time(self):
        localtime = time.asctime(time.localtime(time.time()))
        self.print_log(f'Local current time: {localtime}')

    def print_log(self, s, print_time=True):
        if print_time:
            localtime = time.asctime(time.localtime(time.time()))
            s = f'[ {localtime} ] {s}'
        print(s)
        if self.arg.print_log:
            with open(os.path.join(self.arg.work_dir, 'log.txt'), 'a') as f:
                print(s, file=f)

    def record_time(self):
        self.cur_time = time.time()
        return self.cur_time

    def split_time(self):
        split_time = time.time() - self.cur_time
        self.record_time()
        return split_time

    def save_states(self, epoch, states, out_folder, out_name):
        out_folder_path = os.path.join(self.arg.work_dir, out_folder)
        out_path = os.path.join(out_folder_path, out_name)
        os.makedirs(out_folder_path, exist_ok=True)
        torch.save(states, out_path)

    def save_checkpoint(self, epoch, out_folder='checkpoints'):
        state_dict = {
            'epoch': epoch,
            'optimizer_states': self.optimizer.state_dict(),
            'lr_scheduler_states': self.lr_scheduler.state_dict(),
        }

        checkpoint_name = f'checkpoint-{epoch}-fwbz{self.arg.forward_batch_size}-{int(self.global_step)}.pt'
        self.save_states(epoch, state_dict, out_folder, checkpoint_name)

    def save_weights(self, epoch, out_folder='weights'):
        state_dict = self.model.state_dict()
        weights = OrderedDict([
            [k.split('module.')[-1], v.cpu()]
            for k, v in state_dict.items()
        ])

        # weights_name = f'weights-{epoch}-{int(self.global_step)}.pt'
        weights_name = f'weights-{epoch}.pt'
        self.save_states(epoch, weights, out_folder, weights_name)

    def train(self, epoch, save_model=False):
        self.model.train()
        loader = self.data_loader['train']
        loss_values = []
        acc_values = []
        self.train_writer.add_scalar('epoch', epoch + 1, self.global_step)
        self.record_time()
        timer = dict(dataloader=0.001, model=0.001, statistics=0.001)

        current_lr = self.optimizer.param_groups[0]['lr']
        self.print_log(f'Training epoch: {epoch + 1}, LR: {current_lr:.4f}')

        process = tqdm(loader, dynamic_ncols=True)
        for batch_idx, (data, label, index) in enumerate(process):
            self.global_step += 1
            # get data
            with torch.no_grad():
                data = data.float().cuda(self.output_device)
                label = label.long().cuda(self.output_device)
            timer['dataloader'] += self.split_time()

            # backward
            self.optimizer.zero_grad()

            ############## Gradient Accumulation for Smaller Batches ##############
            real_batch_size = self.arg.forward_batch_size
            splits = len(data) // real_batch_size
            assert len(data) % real_batch_size == 0, \
                'Real batch size should be a factor of arg.batch_size!'

            for i in range(splits):
                left = i * real_batch_size
                right = left + real_batch_size
                batch_data, batch_label = data[left:right], label[left:right]

                # forward
                output = self.model(batch_data)
                if isinstance(output, tuple):
                    output, l1 = output
                    l1 = l1.mean()
                else:
                    l1 = 0

                loss = self.loss(output, batch_label) / splits

                if self.arg.half:
                    with apex.amp.scale_loss(loss, self.optimizer) as scaled_loss:
                        scaled_loss.backward()
                else:
                    loss.backward()

                loss_values.append(loss.item())
                timer['model'] += self.split_time()

                # Display loss
                process.set_description(f'(BS {real_batch_size}) loss: {loss.item():.4f}')

                value, predict_label = torch.max(output, 1)
                acc = torch.mean((predict_label == batch_label).float())
                acc_values.append(acc)

                self.train_writer.add_scalar('acc', acc, self.global_step)
                self.train_writer.add_scalar('loss', loss.item() * splits, self.global_step)
                self.train_writer.add_scalar('loss_l1', l1, self.global_step)

            #####################################

            # torch.nn.utils.clip_grad_norm_(self.model.parameters(), 2)
            self.optimizer.step()

            # statistics
            self.lr = self.optimizer.param_groups[0]['lr']
            self.train_writer.add_scalar('lr', self.lr, self.global_step)
            timer['statistics'] += self.split_time()

            # Delete output/loss after each batch since it may introduce extra mem during scoping
            # https://discuss.pytorch.org/t/gpu-memory-consumption-increases-while-training/2770/3
            del output
            del loss

        # statistics of time consumption and loss
        proportion = {
            k: f'{int(round(v * 100 / sum(timer.values()))):02d}%'
            for k, v in timer.items()
        }

        mean_loss = np.mean(loss_values)
        mean_acc = torch.mean(torch.stack(acc_values))
        num_splits = self.arg.batch_size // self.arg.forward_batch_size
        self.print_log(f'\tMean training loss: {mean_loss:.4f} (BS {self.arg.batch_size}: {mean_loss * num_splits:.4f}).')
        self.print_log(f'\tMean training acc: {mean_acc:.4f}')
        self.print_log('\tTime consumption: [Data]{dataloader}, [Network]{model}'.format(**proportion))

        # PyTorch > 1.2.0: update LR scheduler here with `.step()`
        # and make sure to save the `lr_scheduler.state_dict()` as part of checkpoint

        if (self.lr_scheduler and not self.arg.lr_scheduler == "ReduceLROnPlateau"):
            if (epoch >= self.arg.epoch_warn):
                self.lr_scheduler.step()

        if save_model:
            # save training checkpoint & weights
            self.save_weights(epoch + 1)
            self.save_checkpoint(epoch + 1)

    def eval(self, epoch, save_score=False, loader_name=['test'], wrong_file=None, result_file=None):
        # Skip evaluation if too early
        
        #print ('LOADER_NAME: {}'.format(loader_name))
        #print ('LOADER_NAME len: {}'.format(len(loader_name)))
        #print ('LOADER_NAME type: {}'.format(type(loader_name)))
        
        lst_score = []
        lst_losses = []
        if epoch + 1 < self.arg.eval_start:
            return

        if wrong_file is not None:
            f_w = open(wrong_file, 'w')
        if result_file is not None:
            f_r = open(result_file, 'w')
        with torch.no_grad():
            self.model = self.model.cuda(self.output_device)
            self.model.eval()
            self.print_log(f'Eval epoch: {epoch + 1}')
            for ln_idx, ln in enumerate(loader_name):
                loss_values = []
                score_batches = []
                step = 0
                process = tqdm(self.data_loader[ln], dynamic_ncols=True)
                for batch_idx, (data, label, index) in enumerate(process):   
                    data = data.float().cuda(self.output_device)
                    label = label.long().cuda(self.output_device)
                    output = self.model(data)
                    if isinstance(output, tuple):
                        output, l1 = output
                        l1 = l1.mean()
                    else:
                        l1 = 0
                    loss = self.loss(output, label)
                    score_batches.append(output.data.cpu().numpy())
                    loss_values.append(loss.item())

                    _, predict_label = torch.max(output.data, 1)
                    step += 1

                    if wrong_file is not None or result_file is not None:
                        predict = list(predict_label.cpu().numpy())
                        true = list(label.data.cpu().numpy())
                        for i, x in enumerate(predict):
                            if result_file is not None:
                                f_r.write(str(x) + ',' + str(true[i]) + '\n')
                            if x != true[i] and wrong_file is not None:
                                f_w.write(str(index[i]) + ',' + str(x) + ',' + str(true[i]) + '\n')
                
                score_i = np.concatenate(score_batches)
                lst_score.append(score_i)
                lst_losses.append(np.mean(loss_values))


            score = np.zeros((len(lst_score[0]), len(lst_score[0][0])))
            iter = 0
            for i in tqdm(range(len(lst_score))):
                iter = iter + 1
                score+=lst_score[i]
            score/=iter
            loss = np.mean(lst_losses)
            
            accuracy = self.data_loader[ln].dataset.top_k(np.array(score), 1)
            if accuracy > self.best_acc:
                self.best_acc = accuracy
                self.best_acc_epoch = epoch + 1

            print('Best loss val: ', self.best_loss_val)
            print('Actual loss_val: ', loss)
            if loss > self.best_loss_val and self.best_loss_val != -1:
                self.counter_early_stopping = self.counter_early_stopping + 1 
            else:
                self.counter_early_stopping = 0
                self.best_loss_val = loss
                 

            print('Accuracy: ', accuracy, ' model: ', self.arg.work_dir)
            if self.arg.phase == 'train' and not self.arg.debug:
                self.val_writer.add_scalar('loss', loss, self.global_step)
                self.val_writer.add_scalar('loss_l1', l1, self.global_step)
                self.val_writer.add_scalar('acc', accuracy, self.global_step)

            # score_dict = dict(zip(self.data_loader[ln].dataset.sample_name, score))
            score_dict = dict(zip(self.data_loader[ln].dataset.sample_name[0], score))
            self.print_log(f'\tMean {ln} loss of {len(self.data_loader[ln])} batches: {np.mean(loss_values)}.')
            for k in self.arg.show_topk:
                self.print_log(f'\tTop {k}: {100 * self.data_loader[ln].dataset.top_k(score, k):.2f}%')

            if (self.lr_scheduler and self.arg.lr_scheduler == "ReduceLROnPlateau"):
                self.lr_scheduler.step(loss)


            if save_score:
                with open('{}/epoch{}_test_score.pkl'.format(self.arg.work_dir, epoch + 1), 'wb') as f:
                    pickle.dump(score_dict, f)

        # Empty cache after evaluation
        torch.cuda.empty_cache()



        
    def tta_process_ensemble(lst_score):
        lst_score_ens = [0] * len(lst_score[0])
        for i in tqdm(range(len(lst_score))):
            for score in enumerate(lst_score):
                lst_score_ens[i] = lst_score_ens[i] + score
            
        return lst_score_ens


    def start(self):
        if self.arg.phase == 'train':
            self.print_log(f'Parameters:\n{pprint.pformat(vars(self.arg))}\n')
            self.print_log(f'Model total number of params: {count_params(self.model)}')
            self.global_step = self.arg.start_epoch * len(self.data_loader['train']) / self.arg.batch_size
            for epoch in range(self.arg.start_epoch, self.arg.num_epoch):
                save_model = ((epoch + 1) % self.arg.save_interval == 0) or (epoch + 1 == self.arg.num_epoch)
                self.train(epoch, save_model=save_model)
                self.eval(epoch, save_score=self.arg.save_score, loader_name=self.lst_name_test_tta)

                if (self.arg.early_stopping > 0):   # Default 0 : disabled
                    if self.counter_early_stopping > 0:
                        self.print_log(f'Counter_early_stopping: {self.counter_early_stopping}')
                        if self.counter_early_stopping > self.arg.early_stopping:
                            self.print_log(f'Counter_early_stopping limite detected - Stop training process')
                            break

            num_params = sum(p.numel() for p in self.model.parameters() if p.requires_grad)
            self.print_log(f'Best accuracy: {self.best_acc}')
            self.print_log(f'Epoch number: {self.best_acc_epoch}')
            self.print_log(f'Model name: {self.arg.work_dir}')
            self.print_log(f'Model total number of params: {num_params}')
            self.print_log(f'Weight decay: {self.arg.weight_decay}')
            self.print_log(f'Base LR: {self.arg.base_lr}')
            self.print_log(f'Batch Size: {self.arg.batch_size}')
            self.print_log(f'Forward Batch Size: {self.arg.forward_batch_size}')
            self.print_log(f'Test Batch Size: {self.arg.test_batch_size}')

        elif self.arg.phase == 'test':
            if not self.arg.test_feeder_args['debug']:
                wf = os.path.join(self.arg.work_dir, 'wrong-samples.txt')
                rf = os.path.join(self.arg.work_dir, 'right-samples.txt')
            else:
                wf = rf = None
            if self.arg.weights is None:
                raise ValueError('Please appoint --weights.')

            self.print_log(f'Model:   {self.arg.model}')
            self.print_log(f'Weights: {self.arg.weights}')

            self.eval(
                epoch=0,
                save_score=self.arg.save_score,
                loader_name=self.lst_name_test_tta,
                wrong_file=wf,
                result_file=rf
            )

            self.print_log('Done.\n')


def str2bool(v):
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')


def main():
    parser = get_parser()

    # load arg form config file
    p = parser.parse_args()
    if p.config is not None:
        with open(p.config, 'r') as f:
            default_arg = yaml.safe_load(f)
        key = vars(p).keys()
        for k in default_arg.keys():
            if k not in key:
                print('WRONG ARG:', k)
                assert (k in key)
        parser.set_defaults(**default_arg)

    arg = parser.parse_args()
    print('-------------------')
    print(arg)
    print('-------------------')
    if 'train_feeder_args' in arg:
        if arg.train_feeder_args != {}:
            arg.train_feeder_args['data_path'] = arg.train_feeder_args['data_path'].replace("$STREAM", arg.stream).replace("$DATASET", arg.dataset)
            arg.train_feeder_args['label_path'] = arg.train_feeder_args['label_path'].replace("$STREAM", arg.stream).replace("$DATASET", arg.dataset)
    if 'test_feeder_args' in arg:   
        if arg.test_feeder_args != {}:
            arg.test_feeder_args['data_path'] = arg.test_feeder_args['data_path'].replace("$STREAM", arg.stream).replace("$DATASET", arg.dataset)
            arg.test_feeder_args['label_path'] = arg.test_feeder_args['label_path'].replace("$STREAM", arg.stream).replace("$DATASET", arg.dataset)

    arg.model_args['num_class'] = arg.num_classes

    if ('angles' not in arg.stream):
        arg.model_args['in_channels'] = len(arg.stream.split('_')[-1])
    else:
        if ('angles_extended' in arg.stream):
            arg.model_args['in_channels']  = 4  # angle, cv1, cv2
        else:
            arg.model_args['in_channels']  = 1  # angle, cv1, cv2

    print('CHANGED NUM CLASSES: ', arg.model_args['num_class'])
    print('CHANGED NUM CANALES USADOS: ', arg.model_args['in_channels'])
    

    print('ARG: ', arg)
    if (arg.use_tta == False):
        print('Deactivate tta')
        arg.tta = [arg.tta[0]]
        
    print(arg.tta)

    init_seed(arg)
    processor = Processor(arg)
    processor.start()


if __name__ == '__main__':
    main()