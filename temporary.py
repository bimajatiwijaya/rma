# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import odoo
from odoo import _, api, exceptions, fields, models
from odoo import tools
from odoo.tools.translate import _
from odoo.tools import html2plaintext


class CrmClaimStage(models.Model):
    """ Model for claim stages. This models the main stages of a claim
        management flow. Main CRM objects (leads, opportunities, project
        issues, ...) will now use only stages, instead of state and stages.
        Stages are for example used to display the kanban view of records.
    """
    _name = "crm.claim.stage"
    _description = "Claim stages"
    _rec_name = 'name'
    _order = "sequence"

    name = fields.Char('Stage Name', required=True, translate=True)
    sequence = fields.Integer('Sequence', help="Used to order stages. Lower is better.", default=1)
    team_ids = fields.Many2many('crm.team', 'crm_team_claim_stage_rel', 'stage_id', 'team_id', string='Teams',
                                help="Link between stages and sales teams. When set, this limitate the current stage to the selected sales teams.")
    case_default = fields.boolean('Common to All Teams',
                                  help="If you check this field, this stage will be proposed by default on each sales team. It will not assign this stage to existing teams.")


class CrmClaim(models.Model):
    """ Crm claim
    """
    _name = "crm.claim"
    _description = "Claim"
    _order = "priority,date desc"
    _inherit = ['mail.thread']

    @api.model
    @api.returns('self', lambda value: value.id if value else False)
    def _get_default_stage_id(self):
        """ Gives default stage_id """
        team_id = self.env['crm.team']._get_default_team_id(user_id=self.env.uid)
        return self.stage_find([], team_id, [('sequence', '=', '1')])

    id = fields.Integer('ID', readonly=True)
    name = fields.Char('Claim Subject', required=True)
    active = fields.Boolean('Active', default=True)
    action_next = fields.Char('Next Action')
    date_action_next = fields.Datetime('Next Action Date')
    description = fields.Text('Description')
    resolution = fields.Text('Resolution')
    create_date = fields.Datetime('Creation Date', readonly=True)
    write_date = fields.Datetime('Update Date', readonly=True)
    date_deadline = fields.Date('Deadline')
    date_closed = fields.Datetime('Closed', readonly=True)
    date = fields.Datetime('Claim Date', select=True, default=fields.Datetime.now)
    ref = fields.Reference('Reference', selection=odoo.addons.base.res.res_request.referencable_models)
    categ_id = fields.Many2one('crm.claim.category', 'Category')
    priority = fields.Selection([('0', 'Low'), ('1', 'Normal'), ('2', 'High')], 'Priority', default='1')
    type_action = fields.Selection([('correction', 'Corrective Action'), ('prevention', 'Preventive Action')],
                                   'Action Type')
    user_id = fields.Many2one('res.users', 'Responsible', track_visibility='always', default=lambda self: self.env.uid)
    user_fault = fields.Char('Trouble Responsible')
    team_id = fields.Many2one('crm.team', 'Sales Team', oldname='section_id',
                              select=True, help="Responsible sales team."
                                                " Define Responsible user and Email account for"
                                                " mail gateway.",
                              default=lambda self: self.env['crm.team']._get_default_team_id())
    company_id = fields.Many2one('res.company', 'Company',
                                 default=lambda s: s.env['res.company']._company_default_get('crm.case'))
    partner_id = fields.Many2one('res.partner', 'Partner')
    email_cc = fields.Text('Watchers Emails', size=252,
                           help="These email addresses will be added to the CC field of all inbound and outbound emails for this record before being sent. Separate multiple email addresses with a comma")
    email_from = fields.Char('Email', size=128, help="Destination email for email gateway.")
    partner_phone = fields.char('Phone')
    stage_id = fields.Many2one('crm.claim.stage', 'Stage', track_visibility='onchange',
                               domain="['|', ('team_ids', '=', team_id), ('case_default', '=', True)]",
                               default=lambda s: s._get_default_stage_id())
    cause = fields.Text('Root Cause')

    @api.model
    def stage_find(self, cases, team_id, domain=[], order='sequence'):
        """ Override of the base.stage method
            Parameter of the stage search taken from the lead:
            - team_id: if set, stages must belong to this team or
              be a default case
        """
        if isinstance(cases, (int, long)):
            cases = self.browse(cases)
        # collect all team_ids
        team_ids = []
        if team_id:
            team_ids.append(team_id)
        for claim in cases:
            if claim.team_id:
                team_ids.append(claim.team_id.id)
        # OR all team_ids and OR with case_default
        search_domain = []
        if team_ids:
            search_domain += [('|')] * len(team_ids)
            for team_id in team_ids:
                search_domain.append(('team_ids', '=', team_id))
        search_domain.append(('case_default', '=', True))
        # AND with the domain in parameter
        search_domain += list(domain)
        # perform search, return the first found
        stage_ids = self.env['crm.claim.stage'].search(search_domain, order=order)
        if stage_ids:
            return stage_ids[0]
        return False

    @api.onchange('partner_id')
    def onchange_partner_id(self):
        """This function returns value of partner address based on partner
           :param email: ignored
        """
        if not self.partner_id:
            return {'value': {'email_from': False, 'partner_phone': False}}
        address = self.env['res.partner'].browse([self.partner_id.id])
        return {'value': {'email_from': address.email, 'partner_phone': address.phone}}

    @api.model
    def create(self, vals):
        context = self._context.copy()
        if vals.get('team_id') and not context.get('default_team_id'):
            context['default_team_id'] = vals.get('team_id')

        # context: no_log, because subtype already handle this
        return super(CrmClaim, self).with_context(context).create(vals)

    @api.multi
    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        default['name'] = self.name
        default['stage_id'] = self._get_default_stage_id()
        return super(CrmClaim, self).copy(default=default)

    # -------------------------------------------------------
    # Mail gateway
    # -------------------------------------------------------
    @api.model
    def message_new(self, msg, custom_values=None):
        """ Overrides mail_thread message_new that is called by the mailgateway
            through message_process.
            This override updates the document according to the email.
        """
        create_context = dict(self.env.context or {})
        desc = html2plaintext(msg.get('body')) if msg.get('body') else ''
        defaults = {
            'name': msg.get('subject') or _("No Subject"),
            'description': desc,
            'email_from': msg.get('from'),
            'email_cc': msg.get('cc'),
            'partner_id': msg.get('author_id', False),
        }
        if custom_values:
            defaults.update(custom_values)
        if msg.get('priority'):
            defaults['priority'] = msg.get('priority')
        defaults.update(custom_values)
        return super(CrmClaim, self.with_context(create_context)).message_new(msg, custom_values=defaults)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.multi
    def _claim_count(self):
        Claim = self.env['crm.claim']
        for partner in self:
            partner.claim_count = Claim.search_count(
                ['|', ('partner_id', 'in', partner.child_ids.ids), ('partner_id', '=', partner.id)])

    claim_count = fields.Integer(compute='_claim_count', string='# Claims')


class CrmClaimCategory(models.Model):
    _name = "crm.claim.category"
    _description = "Category of claim"

    name = fields.Char('Name', required=True, translate=True)
    team_id = fields.Many2one('crm.team', 'Sales Team')
