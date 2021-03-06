# -*- coding: utf-8 -*-
# © 2016 Joel Grand-Guillaume, Cyril Gaudin (Camptocamp)
# © 2009-2013 Akretion, Emmanuel Samyn, Raphaël Valyi, Sébastien Beau
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from openerp import fields, models


class ResCompany(models.Model):

    _inherit = "res.company"

    crm_return_address_id = fields.Many2one(
        'res.partner',
        string='Return address',
        help="Default address where the customers has to send back the "
             "returned product. If empty, the address is the "
             "company address")
